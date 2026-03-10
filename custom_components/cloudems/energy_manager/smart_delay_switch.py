# -*- coding: utf-8 -*-
"""
CloudEMS Slimme Uitstelmodus — v1.0.0

Detecteert wanneer een schakelaar AAN gaat tijdens dure stroom en schakelt hem
automatisch UIT. Zodra het geconfigureerde goedkope prijsblok aanbreekt wordt
de schakelaar automatisch weer ingeschakeld.

Werking:
  1. Elke 10s tick: controleer of schakelaar AAN staat én prijs > drempel
  2. Zo ja: schakelaar UIT + status = 'wachtend'
  3. Elke tick: zoek goedkoopste blok in price_info
  4. Als goedkoop blok start (of we zitten er al in): schakelaar AAN
  5. Status terug naar 'idle'

Detectie-opties (combineerbaar):
  - switch_state:   schakelaar entiteit zelf (aan/uit)
  - power_sensor:   vermogenssensor (W) — betrouwbaarder voor always-on apparaten

Configuratie per schakelaar:
  entity_id           str   — te bedienen switch/input_boolean/script
  label               str   — leesbare naam (bijv. "Vaatwasser")
  power_sensor        str?  — optionele vermogenssensor (W)
  power_threshold_w   float — vermogen waarboven "actief" (default: 10 W)
  price_threshold_eur float — prijs waarboven uitschakelen (default: 0.25 €/kWh)
  wait_mode           str   — wachtmodus: "price" (default) of "cheapest_block"
  window_hours        int   — goedkoopste N uur (1–8, zelfde als cheap_switch)
  earliest_hour       int   — niet eerder dan dit uur inschakelen (0–23)
  latest_hour         int   — niet later dan dit uur inschakelen (0–23)
  grace_s             int   — seconden na detectie wachten voor uitschakelen (default: 30)
  notify              bool  — stuur HA persistent_notification (default: True)
  active              bool  — in-/uitschakelen zonder verwijderen

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Cooldown na inschakelen — voorkomt directe herdetectie (seconden)
REARM_COOLDOWN_S = 300   # 5 minuten


def _local_now(hass: HomeAssistant) -> datetime:
    tz_name = getattr(getattr(hass, "config", None), "time_zone", None)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(tz=ZoneInfo(tz_name))
        except Exception:
            pass
        try:
            from dateutil import tz as _tz
            tzinfo = _tz.gettz(tz_name)
            if tzinfo:
                return datetime.now(tz=tzinfo)
        except Exception:
            pass
    return datetime.now()


class DelayState(str, Enum):
    IDLE        = "idle"         # niets aan de hand
    DETECTED    = "detected"     # actief gedetecteerd, grace period loopt
    INTERCEPTED = "intercepted"  # uitgeschakeld, wacht op goedkoop blok
    ACTIVATING  = "activating"   # goedkoop blok gevonden, aan het inschakelen
    CANCELLED   = "cancelled"    # handmatig geannuleerd


@dataclass
class SmartDelayConfig:
    entity_id:          str
    label:              str   = ""
    power_sensor:       Optional[str]  = None
    power_threshold_w:  float = 10.0
    price_threshold_eur:float = 0.25
    window_hours:       int   = 2
    earliest_hour:      int   = 0
    latest_hour:        int   = 23
    grace_s:            int   = 30
    notify:             bool  = True
    active:             bool  = True
    # v4.5: wachtmodus
    # "price"          — wacht tot prijs <= price_threshold_eur (huidige gedrag)
    # "cheapest_block" — wacht altijd tot het goedkoopste N-uursblok start,
    #                    ongeacht of de prijs onder de drempel zakt
    wait_mode:          str   = "price"
    # v4.5: maximale wachttijd
    # 0 = onbeperkt wachten (oorspronkelijk gedrag)
    # >0 = schakel sowieso in na max_wait_h uur, ook als geen goedkoop blok gevonden
    # Beschermt tegen oneindig wachten bij ontbrekende EPEX-data of geen goedkoop blok
    # Typisch: vaatwasser=12h (klaar voor ochtend), wasmachine=8h, EV=0 (onbeperkt)
    max_wait_h:         int   = 0

    @classmethod
    def from_dict(cls, d: dict) -> "SmartDelayConfig":
        return cls(
            entity_id          = d.get("entity_id", ""),
            label              = d.get("label", d.get("entity_id", "")),
            power_sensor       = d.get("power_sensor") or None,
            power_threshold_w  = float(d.get("power_threshold_w", 10.0)),
            price_threshold_eur= float(d.get("price_threshold_eur", 0.25)),
            window_hours       = int(d.get("window_hours", 2)),
            earliest_hour      = int(d.get("earliest_hour", 0)),
            latest_hour        = int(d.get("latest_hour", 23)),
            grace_s            = int(d.get("grace_s", 30)),
            notify             = bool(d.get("notify", True)),
            active             = bool(d.get("active", True)),
            wait_mode          = str(d.get("wait_mode", "price")),
            max_wait_h         = int(d.get("max_wait_h", 0)),
        )

    def to_dict(self) -> dict:
        return {
            "entity_id":          self.entity_id,
            "label":              self.label,
            "power_sensor":       self.power_sensor,
            "power_threshold_w":  self.power_threshold_w,
            "price_threshold_eur":self.price_threshold_eur,
            "window_hours":       self.window_hours,
            "earliest_hour":      self.earliest_hour,
            "latest_hour":        self.latest_hour,
            "grace_s":            self.grace_s,
            "notify":             self.notify,
            "active":             self.active,
            "wait_mode":          self.wait_mode,
            "max_wait_h":         self.max_wait_h,
        }


@dataclass
class SwitchDelayState:
    """Runtime-toestand van één schakelaar."""
    state:          DelayState = DelayState.IDLE
    detected_at:    float = 0.0    # timestamp van detectie
    intercepted_at: float = 0.0    # timestamp van uitschakelen
    activated_at:   float = 0.0    # timestamp van (her)inschakelen
    target_hour:    Optional[int] = None  # gepland startuur van goedkoop blok
    reason:         str = ""


class SmartDelayScheduler:
    """
    Beheert alle slimme uitstelmodus-koppelingen.

    Aanroepen vanuit coordinator (elke 10s):
        result = await scheduler.async_evaluate(price_info)
    """

    def __init__(self, hass: HomeAssistant, configs: list[dict]) -> None:
        self._hass    = hass
        self._configs: list[SmartDelayConfig] = [
            SmartDelayConfig.from_dict(c)
            for c in configs if c.get("entity_id")
        ]
        # Runtime-toestand per entity_id
        self._states: dict[str, SwitchDelayState] = {}
        # Cooldown na (her)inschakelen — voorkomt directe herdetectie
        self._rearm_ts: dict[str, float] = {}

    def update_configs(self, configs: list[dict]) -> None:
        self._configs = [
            SmartDelayConfig.from_dict(c)
            for c in configs if c.get("entity_id")
        ]

    def cancel(self, entity_id: Optional[str] = None) -> list[str]:
        """Annuleer uitgestelde schakelaar(s). Geeft lijst van geannuleerde IDs terug."""
        cancelled = []
        targets = (
            [c for c in self._configs if c.entity_id == entity_id]
            if entity_id
            else self._configs
        )
        for cfg in targets:
            st = self._states.get(cfg.entity_id)
            if st and st.state in (DelayState.DETECTED, DelayState.INTERCEPTED):
                st.state  = DelayState.CANCELLED
                st.reason = "Handmatig geannuleerd"
                cancelled.append(cfg.entity_id)
                _LOGGER.info("SmartDelay: %s geannuleerd", cfg.entity_id)
        return cancelled

    # ── Hulpfuncties ──────────────────────────────────────────────────────────

    def _is_device_active(self, cfg: SmartDelayConfig) -> bool:
        """True als het apparaat aantoonbaar actief is (schakelaar + optioneel vermogen)."""
        sw_state = self._hass.states.get(cfg.entity_id)
        if sw_state is None or sw_state.state in ("unavailable", "unknown"):
            return False

        switch_on = sw_state.state in ("on", "true", "1")

        if cfg.power_sensor:
            pwr_state = self._hass.states.get(cfg.power_sensor)
            if pwr_state and pwr_state.state not in ("unavailable", "unknown", ""):
                try:
                    pwr_w = float(pwr_state.state)
                    # kW→W normalisatie
                    unit = (pwr_state.attributes.get("unit_of_measurement") or "").lower()
                    if unit == "kw" or (unit != "w" and pwr_w < 50 and pwr_w > 0):
                        pwr_w *= 1000.0
                    # Als vermogenssensor beschikbaar: gebruik die als primaire trigger
                    return pwr_w >= cfg.power_threshold_w
                except (ValueError, TypeError):
                    pass
        return switch_on

    def _current_price(self, price_info: dict) -> float:
        return float(price_info.get("current", price_info.get("current_price", 0.0)) or 0.0)

    def _cheap_start_hour(self, cfg: SmartDelayConfig, price_info: dict) -> Optional[int]:
        """Geeft het startuur van het goedkoopste aaneengesloten blok terug, of None.

        prices.py levert cheapest_2h_start / 3h / 4h rechtstreeks.
        Voor 1h, 6h, 8h: bepaal het startuur als het laagste uur in cheapest_Nh_hours,
        of val terug op cheapest_hour_1 (laagste individuele uur).
        Fix v4.5: eerder werd ook gezocht naar "cheapest_Nh_block" key die niet bestaat.
        """
        n = cfg.window_hours
        # Directe _start keys voor 2h/3h/4h
        direct = price_info.get(f"cheapest_{n}h_start")
        if direct is not None:
            return int(direct)
        # Afleiden uit cheapest_Nh_hours (gesorteerde individuele goedkope uren)
        hours_list = price_info.get(f"cheapest_{n}h_hours") or []
        if hours_list:
            return int(min(hours_list))
        # Laatste vangnet: goedkoopste individuele uur
        fallback = price_info.get("cheapest_hour_1")
        return int(fallback) if fallback is not None else None

    def _in_cheap_block(self, cfg: SmartDelayConfig, price_info: dict, now_h: int) -> bool:
        """True als we momenteel in het goedkoopste aaneengesloten blok zitten.

        Fix v4.5: prices.py levert in_cheapest_Nh (bool) voor 1-4h blokken.
        Voor 6h/8h: check of now_h in cheapest_Nh_hours zit.
        Eerder werd gezocht naar "cheapest_Nh_block" met een "hours" lijst —
        die key bestaat niet, waardoor dit altijd False retourneerde.
        """
        n = cfg.window_hours
        # Directe boolean voor 1h–4h
        direct_key = f"in_cheapest_{n}h"
        direct = price_info.get(direct_key)
        if direct is not None:
            return bool(direct)
        # Fallback: check uurlijst
        hours_list = price_info.get(f"cheapest_{n}h_hours") or []
        return now_h in hours_list

    async def _turn_off(self, cfg: SmartDelayConfig) -> bool:
        domain = cfg.entity_id.split(".")[0]
        try:
            await self._hass.services.async_call(
                domain, "turn_off", {"entity_id": cfg.entity_id}, blocking=False
            )
            return True
        except Exception as exc:
            _LOGGER.error("SmartDelay _turn_off %s: %s", cfg.entity_id, exc)
            return False

    async def _turn_on(self, cfg: SmartDelayConfig) -> bool:
        domain = cfg.entity_id.split(".")[0]
        try:
            await self._hass.services.async_call(
                domain, "turn_on", {"entity_id": cfg.entity_id}, blocking=False
            )
            self._rearm_ts[cfg.entity_id] = time.time()
            return True
        except Exception as exc:
            _LOGGER.error("SmartDelay _turn_on %s: %s", cfg.entity_id, exc)
            return False

    async def _notify(self, cfg: SmartDelayConfig, title: str, message: str) -> None:
        if not cfg.notify:
            return
        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title":          title,
                    "message":        message,
                    "notification_id": f"cloudems_smart_delay_{cfg.entity_id.replace('.','_')}",
                },
                blocking=False,
            )
        except Exception:
            pass

    # ── Hoofd-evaluatieloop ────────────────────────────────────────────────────

    async def async_evaluate(self, price_info: dict) -> list[dict]:
        """
        Evalueer alle slimme uitstelmodus-schakelaars.
        Aanroepen elke coordinator-tick (10s).
        Returns lijst van acties voor logging/sensor output.
        """
        if not self._configs:
            return []

        now_local = _local_now(self._hass)
        now_h     = now_local.hour
        now_ts    = time.time()
        price     = self._current_price(price_info)
        actions   = []

        for cfg in self._configs:
            if not cfg.active or not cfg.entity_id:
                continue

            # Zorg dat er een state-object is
            if cfg.entity_id not in self._states:
                self._states[cfg.entity_id] = SwitchDelayState()

            st = self._states[cfg.entity_id]

            # ── CANCELLED: reset na 1 tick ─────────────────────────────────
            if st.state == DelayState.CANCELLED:
                st.state = DelayState.IDLE
                continue

            # ── IDLE: detecteer of apparaat actief wordt tijdens dure stroom ─
            if st.state == DelayState.IDLE:
                # Cooldown na (her)inschakelen door ons
                rearm_ts = self._rearm_ts.get(cfg.entity_id, 0)
                if now_ts - rearm_ts < REARM_COOLDOWN_S:
                    continue

                if not self._is_device_active(cfg):
                    continue

                if price <= cfg.price_threshold_eur:
                    # Stroom is al goedkoop — geen actie nodig
                    continue

                # Tijdvenster: is er überhaupt een goedkoop blok vandaag/morgen?
                start_hour = self._cheap_start_hour(cfg, price_info)
                if start_hour is None:
                    continue

                # Start grace period
                st.state       = DelayState.DETECTED
                st.detected_at = now_ts
                st.target_hour = start_hour
                _mode_label = "goedkoopste blok" if cfg.wait_mode == "cheapest_block"                     else f"prijs ≤ €{cfg.price_threshold_eur:.4f}/kWh"
                st.reason      = (
                    f"Actief gedetecteerd om {now_local.strftime('%H:%M')} "
                    f"— prijs €{price:.4f}/kWh > drempel €{cfg.price_threshold_eur:.4f}/kWh. "
                    f"Wacht op {_mode_label} (goedkoopste {cfg.window_hours}u blok start {start_hour:02d}:00)."
                )
                _LOGGER.info(
                    "SmartDelay: %s gedetecteerd — prijs %.4f > %.4f €/kWh, "
                    "goedkoopste %dh start %02d:00",
                    cfg.label or cfg.entity_id, price, cfg.price_threshold_eur,
                    cfg.window_hours, start_hour,
                )
                actions.append({
                    "entity_id": cfg.entity_id,
                    "label":     cfg.label,
                    "action":    "detected",
                    "price":     price,
                    "target_hour": start_hour,
                    "reason":    st.reason,
                })
                continue

            # ── DETECTED: grace period loopt, na grace_s uitschakelen ─────
            if st.state == DelayState.DETECTED:
                elapsed = now_ts - st.detected_at
                if elapsed < cfg.grace_s:
                    continue  # wacht nog

                # Grace voorbij — uitschakelen
                ok = await self._turn_off(cfg)
                if ok:
                    st.state          = DelayState.INTERCEPTED
                    st.intercepted_at = now_ts
                    _LOGGER.info(
                        "SmartDelay: %s UIT gezet (na %ds grace) — "
                        "wacht op goedkoopste %dh blok (%02d:00)",
                        cfg.label or cfg.entity_id, int(elapsed),
                        cfg.window_hours, st.target_hour or 0,
                    )
                    _wacht_zin = (
                        f"Het apparaat wordt ingeschakeld zodra het goedkoopste "
                        f"{cfg.window_hours}-uurs blok start ({st.target_hour:02d}:00) — "
                        f"ongeacht de absolute prijs."
                        if cfg.wait_mode == "cheapest_block"
                        else
                        f"Het apparaat wordt ingeschakeld om {st.target_hour:02d}:00 "
                        f"zodra de prijs ≤ €{cfg.price_threshold_eur:.4f}/kWh is."
                    )
                    await self._notify(
                        cfg,
                        title=f"⏳ {cfg.label or cfg.entity_id} uitgesteld",
                        message=(
                            f"CloudEMS heeft **{cfg.label or cfg.entity_id}** uitgeschakeld "
                            f"omdat de stroomprijs nu €{price:.4f}/kWh is "
                            f"(drempel: €{cfg.price_threshold_eur:.4f}/kWh).\n\n"
                            f"{_wacht_zin}\n\n"
                            f"Annuleren via CloudEMS → Goedkope Uren → Annuleer uitstel."
                        ),
                    )
                    actions.append({
                        "entity_id": cfg.entity_id,
                        "label":     cfg.label,
                        "action":    "intercepted",
                        "price":     price,
                        "target_hour": st.target_hour,
                        "reason":    f"Uitgeschakeld na {cfg.grace_s}s grace — wacht op {st.target_hour:02d}:00",
                    })
                continue

            # ── INTERCEPTED: wacht op goedkoop blok ──────────────────────
            if st.state == DelayState.INTERCEPTED:
                # Update target_hour elke tick (blok kan verschuiven)
                new_start = self._cheap_start_hour(cfg, price_info)
                if new_start is not None:
                    st.target_hour = new_start

                # Tijdvenster check
                if now_h < cfg.earliest_hour or now_h > cfg.latest_hour:
                    continue

                # ── Max wachttijd deadline ────────────────────────────────────
                # Als max_wait_h > 0: schakel sowieso in na max_wait_h uur,
                # ook als geen goedkoop blok beschikbaar is of prijs nog hoog is.
                # Voorkomt oneindig wachten bij ontbrekende EPEX-data of bij
                # apparaten met een harde deadline (vaatwasser klaar voor ochtend).
                if cfg.max_wait_h > 0 and st.intercepted_at > 0:
                    waited_h = (now_ts - st.intercepted_at) / 3600.0
                    if waited_h >= cfg.max_wait_h:
                        _LOGGER.warning(
                            "SmartDelay: %s max wachttijd overschreden "
                            "(%.1fh >= %dh) — toch inschakelen",
                            cfg.label or cfg.entity_id, waited_h, cfg.max_wait_h,
                        )
                        st.state = DelayState.ACTIVATING
                        ok = await self._turn_on(cfg)
                        if ok:
                            st.state        = DelayState.IDLE
                            st.activated_at = now_ts
                            await self._notify(
                                cfg,
                                title=f"⏰ {cfg.label or cfg.entity_id} ingeschakeld (deadline)",
                                message=(
                                    f"CloudEMS heeft **{cfg.label or cfg.entity_id}** ingeschakeld "
                                    f"omdat de maximale wachttijd van {cfg.max_wait_h} uur bereikt is.\n\n"
                                    f"De stroomprijs is nu €{price:.4f}/kWh. "
                                    f"Geen goedkoper moment kon worden gevonden binnen de deadline."
                                ),
                            )
                            actions.append({
                                "entity_id": cfg.entity_id,
                                "label":     cfg.label,
                                "action":    "deadline_forced",
                                "price":     price,
                                "waited_h":  round(waited_h, 1),
                                "reason":    f"Deadline: {cfg.max_wait_h}h wachttijd bereikt",
                            })
                        else:
                            st.state = DelayState.INTERCEPTED
                        continue

                # ── Wachtmodus ─────────────────────────────────────────────
                # "price"          (default): schakel in zodra prijs <= drempel.
                #                  Gebruikt de goedkoopste-blok start enkel als
                #                  richtpunt; controleert ook prijs op elk moment.
                # "cheapest_block": wacht ALTIJD tot het goedkoopste N-uursblok
                #                  start, ook als de prijs al eerder zakt.
                #                  Garandeert écht het goedkoopste moment van de dag.
                in_block = self._in_cheap_block(cfg, price_info, now_h)
                at_start = (st.target_hour is not None and now_h == st.target_hour)

                if cfg.wait_mode == "cheapest_block":
                    # Strikt: alleen inschakelen als we IN het goedkoopste blok zitten
                    if not in_block:
                        continue
                    # In het blok: inschakelen ongeacht absolute prijs
                    # (het IS al het goedkoopste moment van de beschikbare horizon)
                else:
                    # Modus "price" (default):
                    # in_block of at_start én prijs <= drempel
                    if not (in_block or at_start):
                        continue
                    if price > cfg.price_threshold_eur:
                        continue

                # Inschakelen
                st.state       = DelayState.ACTIVATING
                st.target_hour = now_h
                ok = await self._turn_on(cfg)
                if ok:
                    st.state       = DelayState.IDLE
                    st.activated_at= now_ts
                    _LOGGER.info(
                        "SmartDelay: %s AAN gezet — goedkoop blok %02d:00 "
                        "(prijs €%.4f/kWh)",
                        cfg.label or cfg.entity_id, now_h, price,
                    )
                    await self._notify(
                        cfg,
                        title=f"✅ {cfg.label or cfg.entity_id} ingeschakeld",
                        message=(
                            f"CloudEMS heeft **{cfg.label or cfg.entity_id}** ingeschakeld. "
                            f"De stroomprijs is nu €{price:.4f}/kWh — "
                            f"het goedkoopste {cfg.window_hours}-uurs blok is begonnen."
                        ),
                    )
                    actions.append({
                        "entity_id": cfg.entity_id,
                        "label":     cfg.label,
                        "action":    "activated",
                        "price":     price,
                        "hour":      now_h,
                        "reason":    f"Goedkoop blok gestart ({now_h:02d}:00, €{price:.4f}/kWh)",
                    })
                else:
                    st.state = DelayState.INTERCEPTED  # retry next tick
                continue

        return actions

    # ── Status voor sensor/dashboard ─────────────────────────────────────────

    def get_status(self, price_info: dict) -> list[dict]:
        """Return huidige status van alle schakelaars (voor sensor attribuut)."""
        now_local = _local_now(self._hass)
        now_h     = now_local.hour
        now_ts    = time.time()
        result    = []

        for cfg in self._configs:
            st = self._states.get(cfg.entity_id, SwitchDelayState())
            sw_state = self._hass.states.get(cfg.entity_id)
            current  = sw_state.state if sw_state else "unavailable"

            start_h  = self._cheap_start_hour(cfg, price_info)
            in_block = self._in_cheap_block(cfg, price_info, now_h)

            waiting_min = None
            if st.state == DelayState.INTERCEPTED and st.intercepted_at > 0:
                waiting_min = round((now_ts - st.intercepted_at) / 60, 0)

            result.append({
                "entity_id":          cfg.entity_id,
                "label":              cfg.label or cfg.entity_id,
                "delay_state":        st.state.value,
                "current_switch":     current,
                "price_threshold":    cfg.price_threshold_eur,
                "window_hours":       cfg.window_hours,
                "earliest_hour":      cfg.earliest_hour,
                "latest_hour":        cfg.latest_hour,
                "grace_s":            cfg.grace_s,
                "target_hour":        st.target_hour,
                "cheap_block_start":  start_h,
                "in_cheap_block":     in_block,
                "waiting_min":        waiting_min,
                "reason":             st.reason,
                "active":             cfg.active,
                "notify":             cfg.notify,
                "power_sensor":       cfg.power_sensor,
                "power_threshold_w":  cfg.power_threshold_w,
                "wait_mode":          cfg.wait_mode,
                "max_wait_h":         cfg.max_wait_h,
                "deadline_ts":        (st.intercepted_at + cfg.max_wait_h * 3600)
                                      if (cfg.max_wait_h > 0 and st.intercepted_at > 0)
                                      else None,
            })
        return result
