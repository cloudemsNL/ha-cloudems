# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS — Lamp Automation Engine (v1.0.0).

Volledig los van lamp_circulation.py — beide kunnen onafhankelijk aan/uit.

Modi per lamp:
  manual  — leert alleen, doet niets
  semi    — notificatie met Ja/Nee voor actie
  auto    — direct uitvoeren op basis van geleerd patroon

Ruimte-standaarden (prefill vanuit HA areas):
  slaapkamer/badkamer → manual
  woonkamer/keuken    → semi
  hal/gang/buiten     → auto
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

FORGOTTEN_LIGHT_MINUTES = 30     # lamp uit na X min absent
SEMI_COOLDOWN_S         = 1800   # 30 min cooldown na Nee
AUTO_ON_MIN_SCORE       = 0.45   # minimale geleerde score voor auto-aan
BEDTIME_HOUR            = 23     # geen auto-aan na dit uur
OUTDOOR_OFF_HOUR        = 0      # buiten-lampen uit na middernacht
TICK_INTERVAL_S         = 60     # evaluatie elke minuut

ROOM_DEFAULT_MODE: dict[str, tuple[str, bool]] = {
    # keyword       → (modus,   is_outdoor)
    "slaapkamer":   ("manual",  False),
    "bedroom":      ("manual",  False),
    "badkamer":     ("manual",  False),
    "bathroom":     ("manual",  False),
    "toilet":       ("manual",  False),
    "woonkamer":    ("semi",    False),
    "living":       ("semi",    False),
    "keuken":       ("semi",    False),
    "kitchen":      ("semi",    False),
    "kantoor":      ("semi",    False),
    "office":       ("semi",    False),
    "studeerkamer": ("semi",    False),
    "hal":          ("auto",    False),
    "gang":         ("auto",    False),
    "hallway":      ("auto",    False),
    "tuin":         ("auto",    True),
    "garden":       ("auto",    True),
    "buiten":       ("auto",    True),
    "outdoor":      ("auto",    True),
    "garage":       ("auto",    True),
    "oprit":        ("auto",    True),
}


@dataclass
class LampAutoCfg:
    entity_id:       str
    label:           str            = ""
    mode:            str            = "manual"
    area_id:         str            = ""
    area_name:       str            = ""
    presence_sensor: Optional[str]  = None
    auto_on:         bool           = True
    auto_off:        bool           = True
    outdoor:         bool           = False
    excluded:        bool           = False
    _semi_refused_until: float      = field(default=0.0, repr=False)


class LampAutomationEngine:
    """Slimme lamp-automatisering op basis van geleerd patroon."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass        = hass
        self._config      = config
        self._lamps:      list[LampAutoCfg] = []
        self._enabled     = False
        self._last_tick   = 0.0
        self._notify_svc  = config.get("notification_service", "")
        self._actions_log: list[dict] = []   # laatste 20 acties

    @property
    def enabled(self) -> bool:
        return self._enabled

    def configure(self, lamp_auto_cfg: list[dict]) -> None:
        existing = {l.entity_id: l for l in self._lamps}
        new_lamps = []
        for c in lamp_auto_cfg:
            eid = c.get("entity_id", "")
            if not eid:
                continue
            lamp = existing.get(eid) or LampAutoCfg(entity_id=eid)
            lamp.label           = c.get("label", eid.split(".")[-1].replace("_", " ").title())
            lamp.mode            = c.get("mode", "manual")
            lamp.area_id         = c.get("area_id", "")
            lamp.area_name       = c.get("area_name", "")
            lamp.presence_sensor = c.get("presence_sensor")
            lamp.auto_on         = c.get("auto_on", True)
            lamp.auto_off        = c.get("auto_off", True)
            lamp.outdoor         = c.get("outdoor", False)
            lamp.excluded        = c.get("excluded", False)
            new_lamps.append(lamp)
        self._lamps   = new_lamps
        self._enabled = bool(self._config.get("lamp_auto_enabled")) and bool(new_lamps)
        _LOGGER.info("LampAutomation: %d lampen, enabled=%s", len(self._lamps), self._enabled)

    def build_suggestions(self) -> list[dict]:
        """Bouw prefill-lijst op basis van HA areas en entiteiten."""
        suggestions = []
        try:
            all_states = self._hass.states.async_all()
            areas = self._hass.data.get("area_registry", None)
            area_map: dict[str, str] = {}
            if areas:
                for area in areas.async_list_areas():
                    area_map[area.id] = area.name

            er = self._hass.data.get("entity_registry", None)
            ar = self._hass.data.get("area_registry", None)

            for state in all_states:
                eid = state.entity_id
                if not eid.startswith("light."):
                    continue

                # Area opzoeken via entity registry
                area_id, area_name = "", ""
                if er:
                    entry = er.async_get(eid)
                    if entry and entry.area_id:
                        area_id = entry.area_id
                        area_name = area_map.get(area_id, "")

                # Modus op basis van ruimtenaam
                mode, is_outdoor = "manual", False
                for kw, (m, o) in ROOM_DEFAULT_MODE.items():
                    if kw in area_name.lower():
                        mode, is_outdoor = m, o
                        break

                # Presence sensor in dezelfde ruimte
                presence = None
                if area_id and er:
                    for s2 in all_states:
                        if not s2.entity_id.startswith("binary_sensor."):
                            continue
                        dc = s2.attributes.get("device_class", "")
                        if dc not in ("motion", "occupancy", "presence"):
                            continue
                        e2 = er.async_get(s2.entity_id)
                        if e2 and e2.area_id == area_id:
                            presence = s2.entity_id
                            break

                label = state.attributes.get("friendly_name", "") or eid.split(".")[-1].replace("_", " ").title()
                suggestions.append({
                    "entity_id":       eid,
                    "label":           label,
                    "mode":            mode,
                    "area_id":         area_id,
                    "area_name":       area_name,
                    "presence_sensor": presence,
                    "auto_on":         True,
                    "auto_off":        True,
                    "outdoor":         is_outdoor,
                    "excluded":        False,
                })
        except Exception as err:
            _LOGGER.warning("LampAutomation build_suggestions: %s", err)
        return suggestions

    def auto_configure_from_ha(
        self,
        ha_areas: dict,
        ha_entities: dict,
    ) -> list[dict]:
        """Bouw lamp-lijst op basis van pre-gebouwde area/entity dicts vanuit coordinator.

        ha_areas:    {area_id: {"name": str}}
        ha_entities: {entity_id: {"name": str, "area_id": str, "device_class": str}}
        Retourneert dezelfde structuur als build_suggestions().
        """
        suggestions = []
        try:
            area_map = {aid: info.get("name", "") for aid, info in ha_areas.items()}

            # Bouw presence-sensor lookup: area_id → eerste motion/occupancy/presence sensor
            presence_by_area: dict[str, str] = {}
            for eid, info in ha_entities.items():
                if not eid.startswith("binary_sensor."):
                    continue
                dc = info.get("device_class", "")
                if dc not in ("motion", "occupancy", "presence"):
                    continue
                aid = info.get("area_id", "")
                if aid and aid not in presence_by_area:
                    presence_by_area[aid] = eid

            for eid, info in ha_entities.items():
                if not eid.startswith("light."):
                    continue

                area_id   = info.get("area_id", "") or ""
                area_name = area_map.get(area_id, "")
                label     = info.get("name", "") or eid.split(".")[-1].replace("_", " ").title()

                # Modus op basis van ruimtenaam
                mode, is_outdoor = "manual", False
                for kw, (m, o) in ROOM_DEFAULT_MODE.items():
                    if kw in area_name.lower():
                        mode, is_outdoor = m, o
                        break

                suggestions.append({
                    "entity_id":       eid,
                    "label":           label,
                    "mode":            mode,
                    "area_id":         area_id,
                    "area_name":       area_name,
                    "presence_sensor": presence_by_area.get(area_id),
                    "auto_on":         True,
                    "auto_off":        True,
                    "outdoor":         is_outdoor,
                    "excluded":        False,
                })
        except Exception as err:
            _LOGGER.warning("LampAutomation auto_configure_from_ha: %s", err)
        return suggestions

    async def async_tick(
        self,
        absence_state: str,
        sun_below_horizon: bool,
        current_hour: int,
        lamp_learner,   # LampCirculationController met _lamps + mimicry_score
        generator_active: bool = False,
        ups_active: bool = False,
    ) -> dict:
        """Hoofd-tick: evalueer elke lamp en voer acties uit.

        Wordt elke minuut aangeroepen vanuit de coordinator.
        Geeft status dict terug voor sensor.
        """
        if not self._enabled:
            return {"enabled": False, "actions": []}

        now_ts  = time.time()
        actions = []
        home    = absence_state in ("home",)
        asleep  = absence_state in ("sleeping",)
        away    = absence_state in ("away", "vacation")
        is_night = current_hour >= BEDTIME_HOUR or current_hour < 6

        # ── UPS-fase: veiligheidsverlichting forceren ─────────────────────────
        if ups_active:
            actions += await self._handle_ups_phase()
            return {
                "enabled":   self._enabled,
                "actions":   actions,
                "ups_active": True,
                "generator_active": False,
            }

        for lamp in self._lamps:
            if lamp.excluded or lamp.mode == "manual":
                continue

            # ── Generator-modus: besparen ─────────────────────────────────────
            if generator_active:
                await self._handle_generator_mode(lamp, actions)
                continue

            # Haal huidige lamp-status op
            state = self._hass.states.get(lamp.entity_id)
            if state is None:
                continue
            is_on = state.state == "on"

            # Ruimte-aanwezigheid check
            room_occupied = self._check_room_presence(lamp)

            # ── AUTO-UIT: vergeten lichten ────────────────────────────────────
            if lamp.auto_off_enabled and is_on:
                forgot = await self._check_forgotten(lamp, away, asleep, now_ts)
                if forgot:
                    await self._do_action(lamp, False, "Vergeten licht — niemand aanwezig", actions)
                    continue

            # ── BUITEN: zonsondergang tot middernacht ─────────────────────────
            if lamp.outdoor:
                if sun_below_horizon and current_hour < OUTDOOR_OFF_HOUR and (home or room_occupied):
                    if not is_on and lamp.auto_on_enabled:
                        await self._trigger(lamp, True, "Buitenverlichting bij zonsondergang",
                                           actions, now_ts)
                elif is_on and (not sun_below_horizon or current_hour >= OUTDOOR_OFF_HOUR):
                    if lamp.auto_off_enabled:
                        await self._do_action(lamp, False, "Buitenverlichting uit (ochtend of middernacht)",
                                             actions)
                continue

            # ── NIEMAND THUIS: alles uit ──────────────────────────────────────
            if away and is_on and lamp.auto_off_enabled:
                await self._do_action(lamp, False, "Niemand thuis — lamp uit", actions)
                continue

            # Geen auto-aan als niemand thuis, slapend of al laat
            if (away or asleep or is_night) and not is_on:
                continue

            # ── AANWEZIG + RUIMTE BEZET: mogelijk auto-aan ───────────────────
            if home and lamp.auto_on_enabled and not is_on and sun_below_horizon:
                # Haal geleerde score op uit de lamp circulation learner
                score = self._get_learner_score(lamp, current_hour, lamp_learner)
                if score >= AUTO_ON_MIN_CONFIDENCE:
                    await self._trigger(lamp, True,
                                       f"Geleerd patroon ({score:.0%} kans)",
                                       actions, now_ts)

            # ── AUTO-UIT op basis van geleerd patroon ────────────────────────
            if is_on and lamp.auto_off_enabled and not is_night:
                score = self._get_learner_score(lamp, current_hour, lamp_learner)
                # Als score heel laag is op dit uur → lamp waarschijnlijk vergeten
                if score < 0.10 and home:
                    await self._trigger(lamp, False,
                                       f"Buiten normaal gebruikspatroon ({score:.0%})",
                                       actions, now_ts)

        return {
            "enabled":  self._enabled,
            "actions":  actions,
            "home":     home,
            "away":     away,
            "asleep":   asleep,
        }

    async def _check_forgotten(self, lamp: LampAutomationConfig,
                                away: bool, asleep: bool, now_ts: float) -> bool:
        """True als lamp vergeten aan staat terwijl niemand aanwezig is."""
        if not (away or asleep):
            return False
        state = self._hass.states.get(lamp.entity_id)
        if state is None or state.state != "on":
            return False
        # Hoe lang al aan?
        try:
            last_changed = state.last_changed.timestamp()
            minutes_on   = (now_ts - last_changed) / 60
        except Exception:
            return False
        return minutes_on >= FORGOTTEN_LIGHT_MINUTES

    async def _trigger(self, lamp: LampAutomationConfig, turn_on: bool,
                       reason: str, actions: list, now_ts: float) -> None:
        """Voer actie uit of vraag bevestiging afhankelijk van modus."""
        # Cooldown check
        if now_ts - lamp._last_auto_action < 300:  # 5 min
            return

        # Ruimte-aanwezigheid check voor aan-acties
        if turn_on and not self._check_room_presence(lamp):
            # Geen beweging in ruimte → alleen als home én geen presence sensor
            if lamp.presence_sensor:
                return  # presence sensor zegt niets → doe niets

        if lamp.mode == "auto":
            await self._do_action(lamp, turn_on, reason, actions)

        elif lamp.mode == "semi":
            # Cooldown na weigering
            if turn_on and now_ts < lamp._semi_refused_until:
                return
            await self._send_confirmation_request(lamp, turn_on, reason, actions)

    async def _do_action(self, lamp: LampAutomationConfig, turn_on: bool,
                         reason: str, actions: list) -> None:
        """Voer lamp-actie direct uit."""
        service = "turn_on" if turn_on else "turn_off"
        try:
            await self._hass.services.async_call(
                "light", service,
                {"entity_id": lamp.entity_id},
                blocking=False,
            )
            lamp._last_auto_action = time.time()
            action_str = "aan" if turn_on else "uit"
            _LOGGER.info("LampAutomation: %s %s — %s", lamp.label, action_str, reason)
            actions.append({
                "entity_id": lamp.entity_id,
                "label":     lamp.label,
                "action":    "on" if turn_on else "off",
                "reason":    reason,
                "mode":      lamp.mode,
                "ts":        time.time(),
            })
        except Exception as err:
            _LOGGER.warning("LampAutomation: actie mislukt voor %s: %s", lamp.entity_id, err)

    async def _send_confirmation_request(self, lamp: LampAutomationConfig,
                                          turn_on: bool, reason: str,
                                          actions: list) -> None:
        """Stuur een HA notificatie met Ja/Nee actie knoppen (semi-modus)."""
        action_str = "aanzetten" if turn_on else "uitzetten"
        msg = (
            f"CloudEMS wil **{lamp.label}** {action_str}.\n"
            f"Reden: {reason}\n\n"
            f"Kies hieronder of druk op Nee om 30 min te wachten."
        )
        notify_data = {
            "message":    msg,
            "title":      f"💡 {lamp.label} {action_str}?",
            "data": {
                "actions": [
                    {"action": f"LAMP_YES_{lamp.entity_id.replace('.','_')}",
                     "title": "✅ Ja"},
                    {"action": f"LAMP_NO_{lamp.entity_id.replace('.','_')}",
                     "title": "❌ Nee (30 min)"},
                    {"action": f"LAMP_AUTO_{lamp.entity_id.replace('.','_')}",
                     "title": "🤖 Altijd automatisch"},
                ]
            }
        }

        if self._notify_svc:
            try:
                svc_parts = self._notify_svc.split(".")
                domain  = svc_parts[0] if len(svc_parts) > 1 else "notify"
                service = svc_parts[1] if len(svc_parts) > 1 else svc_parts[0]
                await self._hass.services.async_call(
                    domain, service, notify_data, blocking=False
                )
            except Exception as err:
                _LOGGER.warning("LampAutomation: notificatie mislukt: %s", err)

        lamp._last_auto_action = time.time()
        actions.append({
            "entity_id": lamp.entity_id,
            "label":     lamp.label,
            "action":    "confirm_request",
            "intent":    "on" if turn_on else "off",
            "reason":    reason,
            "mode":      "semi",
            "ts":        time.time(),
        })

    def handle_confirmation_response(self, action_str: str) -> None:
        """Verwerk reactie op semi-modus notificatie.

        action_str formaat: LAMP_YES_light_woonkamer /
                            LAMP_NO_light_woonkamer /
                            LAMP_AUTO_light_woonkamer
        """
        if not action_str.startswith(("LAMP_YES_", "LAMP_NO_", "LAMP_AUTO_")):
            return
        parts    = action_str.split("_", 2)
        response = parts[1]   # YES / NO / AUTO
        eid_slug = parts[2].replace("_", ".", 1)   # light_woonkamer → light.woonkamer

        lamp = next((l for l in self._lamps if l.entity_id == eid_slug), None)
        if lamp is None:
            return

        if response == "NO":
            lamp._semi_refused_until = time.time() + SEMI_COOLDOWN_S
            _LOGGER.info("LampAutomation: %s geweigerd — 30 min cooldown", lamp.label)

        elif response == "YES":
            # Direct uitvoeren
            self._hass.async_create_task(
                self._do_action(lamp, True, "Bevestigd door gebruiker", [])
            )

        elif response == "AUTO":
            # Upgrade naar automatisch
            lamp.mode = "auto"
            _LOGGER.info("LampAutomation: %s upgrade naar auto-modus", lamp.label)
            self._hass.async_create_task(
                self._do_action(lamp, True, "Upgrade naar auto bevestigd", [])
            )

    def _check_room_presence(self, lamp: LampAutomationConfig) -> bool:
        """Check presence sensor in de ruimte als die geconfigureerd is."""
        if not lamp.presence_sensor:
            return True  # geen sensor = aannemen dat bezet
        st = self._hass.states.get(lamp.presence_sensor)
        if st is None:
            return True
        return st.state in ("on", "home", "detected", "true", "1")

    def _get_learner_score(self, lamp: LampAutomationConfig,
                            hour: int, lamp_learner) -> float:
        """Haal mimicry-score op uit de LampCirculationController."""
        if lamp_learner is None:
            return 0.0
        try:
            dow = datetime.now().weekday()
            # Zoek de LampEntry in de circulation controller
            lc_lamp = next(
                (l for l in lamp_learner._lamps if l.entity_id == lamp.entity_id),
                None
            )
            if lc_lamp is None:
                return 0.0
            return lc_lamp.mimicry_score(hour, dow)
        except Exception:
            return 0.0

    async def _handle_ups_phase(self) -> list:
        """UPS-fase: forceer veiligheidsverlichting aan, rest uit.

        Hal/gang/trap aan zodat bewoners de generator kunnen bereiken.
        Al het andere uit om de UPS-capaciteit te sparen.
        """
        actions = []
        for lamp in self._lamps:
            if lamp.excluded:
                continue
            state = self._hass.states.get(lamp.entity_id)
            if state is None:
                continue
            is_on   = state.state == "on"
            is_safe = any(kw in (lamp.area_name or "").lower() for kw in SAFETY_LIGHT_AREAS)

            if is_safe and not is_on:
                # Veiligheidsverlichting AAN
                await self._do_action(lamp, True, "UPS actief — veiligheidsverlichting", actions)
            elif not is_safe and is_on:
                # Al het andere UIT
                await self._do_action(lamp, False, "UPS actief — stroom besparen", actions)

        if not any(a["action"] == "on" for a in actions):
            _LOGGER.info("LampAutomation UPS: geen veiligheidslampen geconfigureerd (hal/gang/trap)")

        # Stuur notificatie
        await self._send_ups_notification()
        return actions

    async def _send_ups_notification(self) -> None:
        """Stuur UPS-fase melding met instructies."""
        if not self._notify_svc:
            return
        try:
            svc_parts = self._notify_svc.split(".")
            domain  = svc_parts[0] if len(svc_parts) > 1 else "notify"
            service = svc_parts[1] if len(svc_parts) > 1 else svc_parts[0]
            await self._hass.services.async_call(
                domain, service,
                {
                    "title": "🔦 Netuitval — UPS actief",
                    "message": (
                        "CloudEMS heeft netuitval gedetecteerd. "
                        "Veiligheidsverlichting (hal/gang/trap) is ingeschakeld. "
                        "Niet-essentiële lampen zijn uitgeschakeld om UPS te sparen. "
                        "Start de generator of schakel de MTS om."
                    ),
                },
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning("LampAutomation: UPS notificatie mislukt: %s", err)

    async def _handle_generator_mode(self, lamp: LampAutomationConfig,
                                      actions: list) -> None:
        """Generator-modus: bespaar stroom, tuin uit, essentieel normaal."""
        state = self._hass.states.get(lamp.entity_id)
        if state is None:
            return
        is_on = state.state == "on"

        # Buiten/tuin: uitzetten bij generator
        if lamp.outdoor and is_on and GENERATOR_OUTDOOR_OFF:
            await self._do_action(lamp, False,
                                  "Generator actief — buitenverlichting uit", actions)
            return

        # Niet-essentieel: geen auto-aan bij generator
        # (we doen niets — generator-modus blokkeert nieuwe auto-acties)
        # Vergeten lichten bij generator ook uitdoen
        if is_on:
            room_present = self._check_room_presence(lamp)
            if not room_present and lamp.auto_off_enabled:
                await self._do_action(lamp, False,
                                      "Generator actief — niemand in ruimte", actions)

    def get_status(self) -> dict:
        """Geef status dict voor sensor."""
        return {
            "enabled":    self._enabled,
            "lamp_count": len(self._lamps),
            "auto_count": sum(1 for l in self._lamps if l.mode == "auto" and not l.excluded),
            "semi_count": sum(1 for l in self._lamps if l.mode == "semi" and not l.excluded),
            "lamps": [
                {
                    "entity_id":   l.entity_id,
                    "label":       l.label,
                    "mode":        l.mode,
                    "area":        l.area_name,
                    "outdoor":     l.outdoor,
                    "excluded":    l.excluded,
                    "has_presence":bool(l.presence_sensor),
                }
                for l in self._lamps if not l.excluded
            ],
        }
