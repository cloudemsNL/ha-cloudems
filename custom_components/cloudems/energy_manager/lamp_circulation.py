# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS LampCirculation — v3.0.0.

Intelligente lampenbeveiliging + energiebesparing op basis van afwezigheidsdetectie.

Functies (v3)
-------------
• Energiebesparing        — alle lampen uit als niemand thuis
• Inbraakbeveiliging      — DYNAMISCHE circulatie: wisselend 1-3 lampen tegelijk,
                            onregelmatige tijden (2-8 min), echt onvoorspelbaar
• Testmodus               — handmatige activatie ongeacht afwezigheid (2 min)
• Lamp-excludes           — specifieke lampen worden overgeslagen
• Fase-detectie bijvangst — netfase passief gemeten bij elke schakelactie
• NILM registratie        — lampvermogen doorgegeven aan NILM
• Seizoensintelligentie   — nacht afgeleid van zonsondergang (sun.sun entity)
• Leerpatroon-mimicry     — echt bewonersgedrag geleerd + nagebootst
• Buur-lamp correlatie    — timing verschuift als buren lampen aandoen
• Bewegingsmelder bypass  — PIR-sensor check voor lamp uitsluiting
• Energieprijskoppeling   — langere circulatie bij negatieve EPEX prijs

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable

_LOGGER = logging.getLogger(__name__)

# ── Timing parameters ──────────────────────────────────────────────────────────
MIN_STEP_S              = 120    # minimale staptijd (2 min)
MAX_STEP_S              = 480    # maximale staptijd (8 min)
NEG_PRICE_STEP_BONUS_S  = 300    # bij negatieve prijs: extra 5 min
MIN_AWAY_MINUTES        = 5
PHASE_SETTLE_S          = 8
TEST_DURATION_S         = 120
MAX_LAMPS_ON            = 3
PHASE_MIN_DELTA_A       = 0.05
SUN_OFFSET_MIN          = 20     # start circulatie X min na zonsondergang
LEARN_SLOTS             = 24 * 7 # uur-slots per week voor patroon-leer
NEIGHBOR_WINDOW_S       = 180    # venster waarbinnen buur-lamp correlatie geldt
NEIGHBOR_SHIFT_S        = 45     # verschuif eigen timing met max N sec
PIR_BLOCK_S             = 300    # als PIR recent actief was: lamp uitsluiten N sec


@dataclass
class LampEntry:
    """Eén lamp in het systeem."""
    entity_id:          str
    label:              str              = ""
    excluded:           bool             = False
    pir_entity:         Optional[str]    = None   # bewegingsmelder koppelement
    detected_phase:     Optional[str]    = None
    phase_confidence:   float            = 0.0
    nilm_power_w:       Optional[float]  = None
    # Bewonerspatroon: gemiddelde aan-tijd per uur-slot
    _usage_slots:       list             = field(default_factory=lambda: [0.0] * LEARN_SLOTS)
    _usage_counts:      list             = field(default_factory=lambda: [0] * LEARN_SLOTS)
    _pir_last_active:   float            = 0.0

    def __post_init__(self):
        if not self.label:
            self.label = self.entity_id.split(".")[-1].replace("_", " ").title()

    def learn_on(self, hour: int, dow: int) -> None:
        """Registreer dat deze lamp aanging op dit tijdstip."""
        slot = dow * 24 + hour
        n = self._usage_counts[slot]
        alpha = 0.3 if n < 5 else (0.1 if n < 20 else 0.03)
        self._usage_slots[slot] = alpha * 1.0 + (1 - alpha) * self._usage_slots[slot]
        self._usage_counts[slot] = min(n + 1, 9999)

    def mimicry_score(self, hour: int, dow: int) -> float:
        """Hoe waarschijnlijk is het dat bewoners dit licht nu zelf zouden aandoen? 0-1."""
        slot = dow * 24 + hour
        # Kijk ook naar naburige uren voor soepelheid
        scores = []
        for dh in (-1, 0, 1):
            s = (slot + dh) % LEARN_SLOTS
            scores.append(self._usage_slots[s])
        return max(scores)

    def pir_blocked(self, now: float) -> bool:
        """True als de PIR recent actief was (beweging gedetecteerd → IEMAND THUIS)."""
        return (now - self._pir_last_active) < PIR_BLOCK_S


@dataclass
class CirculationStatus:
    """Volledige runtime-status."""
    enabled:              bool
    active:               bool
    test_mode:            bool
    mode:                 str
    reason:               str
    lamps_on:             list[str]
    lamps_on_labels:      list[str]
    next_switch_in_s:     int
    lamps_registered:     int
    lamps_active:         int
    lamps_excluded:       int
    lamps_with_phase:     int
    occupancy_state:      str
    occupancy_confidence: float
    advice:               str
    phase_tip:            str
    mimicry_active:       bool
    neg_price_active:     bool
    sun_derived_night:    bool
    lamp_phases:          list[dict]


class LampCirculationController:
    """
    Intelligente lampenbeveiliging v3 — volledig zelflerend en context-bewust.
    """

    def __init__(self, hass) -> None:
        self.hass               = hass
        self._lamps:            list[LampEntry]   = []
        self._enabled:          bool              = False  # standaard UIT tot configure() het expliciet aanzet
        self._enabled_explicit: bool              = False   # True zodra set_enabled() ooit geroepen is
        self._min_confidence:   float             = 0.55
        self._night_start:      int               = 22
        self._night_end:        int               = 7
        # Runtime
        self._current_on:       set[str]          = set()
        self._away_since:       Optional[float]   = None
        self._next_switch:      float             = 0.0
        self._test_until:       float             = 0.0
        self._test_active:      bool              = False
        # Fase-probe
        self._probe_entity:     Optional[str]     = None
        self._probe_pre:        dict              = {}
        self._probe_time:       float             = 0.0
        self._last_phase_tip:   str               = ""
        # Context-signalen
        self._neg_price_active: bool              = False
        self._sun_derived_night: bool             = False
        # Buurt-correlatie: tijdstempel van laatste externe lamp-activiteit
        self._neighbor_last_t:  float             = 0.0
        # NILM callback
        self._nilm_register_cb: Optional[Callable] = None

    # ── Configuratie ──────────────────────────────────────────────────────────

    def configure(
        self,
        light_entities:  list[str],
        excluded_ids:    list[str]       = None,
        pir_map:         dict            = None,   # {light_eid: pir_eid}
        enabled:         bool            = True,
        min_confidence:  float           = 0.55,
        night_start_h:   int             = 22,
        night_end_h:     int             = 7,
    ) -> None:
        self._min_confidence = min_confidence
        self._night_start    = night_start_h
        self._night_end      = night_end_h
        # _enabled alleen overschrijven als set_enabled() nog nooit expliciet geroepen is.
        # Zo voorkomt een herhaalde configure()-aanroep (lazy-discovery) dat een
        # bewust uitgeschakelde module stiekem weer ingeschakeld wordt.
        if not self._enabled_explicit:
            self._enabled = enabled
        excluded = set(excluded_ids or [])
        pir_map  = pir_map or {}

        existing = {e.entity_id: e for e in self._lamps}
        new_lamps: list[LampEntry] = []
        for eid in light_entities:
            lamp = existing.get(eid, LampEntry(entity_id=eid))
            lamp.excluded   = eid in excluded
            lamp.pir_entity = pir_map.get(eid)
            new_lamps.append(lamp)
        self._lamps = new_lamps

        _LOGGER.info(
            "LampCirculation v3: %d lampen (%d uitgesloten, %d met PIR), conf≥%.0f%%",
            len(self._lamps),
            sum(1 for l in self._lamps if l.excluded),
            sum(1 for l in self._lamps if l.pir_entity),
            min_confidence * 100,
        )

    def set_enabled(self, enabled: bool) -> None:
        self._enabled_explicit = True   # beschermt tegen configure()-overschrijving
        if self._enabled != enabled:
            _LOGGER.info("LampCirculation: %s", "✅ ingeschakeld" if enabled else "❌ uitgeschakeld")
        self._enabled = enabled

    def register_nilm_callback(self, cb: Callable) -> None:
        self._nilm_register_cb = cb

    # ── Externe context-injecties ─────────────────────────────────────────────

    def update_price_context(self, negative_price_active: bool) -> None:
        """Aanroepen vanuit coordinator als EPEX-prijs negatief is."""
        self._neg_price_active = negative_price_active

    def update_neighbor_activity(self, neighbor_lamp_on: bool) -> None:
        """
        Aanroepen als een buur-lamp zojuist aanging (bijv. via HA neighbor group).
        Verschuift eigen volgende schakelmoment met een willekeurige offset.
        """
        if neighbor_lamp_on:
            self._neighbor_last_t = time.time()
            # Verschuif timing zodat we NIET gelijktijdig schakelen
            shift = random.randint(15, NEIGHBOR_SHIFT_S)
            self._next_switch += shift
            _LOGGER.debug(
                "LampCirculation: buur-activiteit gedetecteerd → timing verschoven +%ds", shift
            )

    # ── Test API ──────────────────────────────────────────────────────────────

    async def async_start_test(self) -> str:
        """Start testmodus: zet eerst alle lampen even aan, dan uit, dan start circulatie.
        Bij elke klik op Test wordt de volgende lamp in de rij gekozen."""
        import asyncio

        active = [l for l in self._lamps if not l.excluded]
        if not active:
            return "Geen lampen beschikbaar om te testen."

        # Stap 1: alle lampen aan (visuele bevestiging dat alles werkt)
        for lamp in active:
            await self._set_light(lamp.entity_id, True)

        await asyncio.sleep(1.5)

        # Stap 2: alle lampen uit
        for lamp in active:
            await self._set_light(lamp.entity_id, False)

        await asyncio.sleep(0.5)

        # Stap 3: kies de volgende lamp in de rij (rondgaand)
        # Zoek huidige testlamp-index en zet de volgende aan
        if not hasattr(self, "_test_lamp_index"):
            self._test_lamp_index = 0
        else:
            self._test_lamp_index = (self._test_lamp_index + 1) % len(active)

        next_lamp = active[self._test_lamp_index]
        await self._set_light(next_lamp.entity_id, True)
        self._current_on = {next_lamp.entity_id}

        # Start circulatie
        self._test_until  = time.time() + TEST_DURATION_S
        self._test_active = True
        self._next_switch = time.time() + 10   # eerste wissel na 10s

        _LOGGER.info(
            "LampCirculation: TESTMODUS gestart — lamp '%s' aan, wissel over 10s (%ds totaal)",
            next_lamp.label, TEST_DURATION_S,
        )
        return f"Test gestart — '{next_lamp.label}' aan, circulatie loopt {TEST_DURATION_S}s"

    async def async_stop_test(self) -> None:
        self._test_until  = 0.0
        self._test_active = False
        await self._turn_all_off()

    # ── Hoofdlogica ───────────────────────────────────────────────────────────

    async def async_tick(
        self,
        occupancy_state:      str,
        occupancy_confidence: float,
        phase_currents:       Optional[dict] = None,
        current_price_eur:    Optional[float] = None,
        negative_price:       bool            = False,
    ) -> CirculationStatus:
        """Aanroepen elke coordinator-cyclus (~10 s)."""
        now  = time.time()
        dt   = datetime.now()
        hour = dt.hour
        dow  = dt.weekday()

        # Prijs-context updaten
        if current_price_eur is not None:
            self._neg_price_active = negative_price or (current_price_eur < 0)

        # Fase-probe bijvangst
        if self._probe_entity and phase_currents:
            if now - self._probe_time >= PHASE_SETTLE_S:
                self._finalize_phase_probe(phase_currents)

        # PIR-sensoren lezen + patroonleer uit HA state
        self._update_pir_states(now)
        self._learn_from_ha_states(hour, dow)

        # Zongebaseerde nacht bepalen
        self._sun_derived_night = self._is_sun_night(hour)

        # Geen lampen
        if not self._lamps:
            return self._status(False, "off", "Geen lampen geconfigureerd.",
                               occupancy_state, occupancy_confidence)

        # Uitgeschakeld — ALTIJD als eerste functionele check, ook boven testmodus
        if not self._enabled:
            if self._test_active:
                await self.async_stop_test()
            elif self._current_on:
                await self._turn_all_off()
            return self._status(False, "off", "Lampcirculatie uitgeschakeld.",
                               occupancy_state, occupancy_confidence)

        # Testmodus
        if self._test_active:
            if now > self._test_until:
                await self.async_stop_test()
                # Terugkeren na afloop test — géén doorval naar normale circulatie
                return self._status(False, "off", "Testmodus afgelopen.",
                                   occupancy_state, occupancy_confidence)
            return await self._run_circulation(
                now, hour, dow, phase_currents,
                mode="test",
                reason=f"Testmodus — nog {int(self._test_until - now)}s",
                occupancy_state=occupancy_state,
                occupancy_confidence=occupancy_confidence,
            )

        # Nachtmodus (gecombineerd: configuratie-uur + zonsondergang)
        is_night = self._sun_derived_night or (hour >= self._night_start or hour < self._night_end)
        if is_night:
            if self._current_on:
                await self._turn_all_off()
            night_src = "zon" if self._sun_derived_night else f"{self._night_start}:00"
            return self._status(False, "night_off",
                               f"Nachtmodus (sinds {night_src}).",
                               occupancy_state, occupancy_confidence)

        # Afwezigheidscontrole
        is_away = (
            occupancy_state in ("away", "vacation")
            and occupancy_confidence >= self._min_confidence
        )
        if not is_away:
            if self._current_on:
                await self._turn_all_off()
            self._away_since = None
            reason = (
                "Iemand thuis — circulatie inactief."
                if occupancy_state in ("home", "sleeping")
                else f"Onvoldoende zekerheid ({occupancy_confidence:.0%} < {self._min_confidence:.0%})."
            )
            return self._status(False, "off", reason, occupancy_state, occupancy_confidence)

        # Minimale wachttijd
        if self._away_since is None:
            self._away_since = now
        away_min = (now - self._away_since) / 60
        if away_min < MIN_AWAY_MINUTES:
            return self._status(False, "energy_saving",
                               f"Wacht op bevestiging ({away_min:.1f}/{MIN_AWAY_MINUTES} min).",
                               occupancy_state, occupancy_confidence)

        # Circulatie
        return await self._run_circulation(
            now, hour, dow, phase_currents,
            mode="circulation",
            reason=f"Afwezig {away_min:.0f} min (conf {occupancy_confidence:.0%}).",
            occupancy_state=occupancy_state,
            occupancy_confidence=occupancy_confidence,
        )

    # ── Circulatie kernel ─────────────────────────────────────────────────────

    async def _run_circulation(
        self, now: float, hour: int, dow: int, phase_currents,
        mode: str, reason: str, occupancy_state: str, occupancy_confidence: float,
    ) -> CirculationStatus:
        # Sluit lampen uit waarbij PIR recent actief was
        active_lamps = [
            l for l in self._lamps
            if not l.excluded and not l.pir_blocked(now)
        ]
        if not active_lamps:
            active_lamps = [l for l in self._lamps if not l.excluded]
            if not active_lamps:
                return self._status(False, "off", "Alle lampen uitgesloten.",
                                   occupancy_state, occupancy_confidence)

        if now >= self._next_switch:
            await self._do_switch(active_lamps, hour, dow, phase_currents)

        next_in = max(0, int(self._next_switch - now))
        on_labels = [
            next((l.label for l in self._lamps if l.entity_id == eid), eid)
            for eid in self._current_on
        ]

        # Mimicry: zijn we nu actief op een tijdstip dat bewoners zelf lampen aan zouden hebben?
        mimicry_active = any(
            l.mimicry_score(hour, dow) > 0.3
            for l in self._lamps if l.entity_id in self._current_on
        )

        return self._status(
            True, mode, reason, occupancy_state, occupancy_confidence,
            lamps_on=list(self._current_on),
            lamps_on_labels=on_labels,
            next_switch_in_s=next_in,
            mimicry_active=mimicry_active,
        )

    async def _do_switch(
        self,
        active_lamps: list[LampEntry],
        hour: int, dow: int,
        phase_currents,
    ) -> None:
        """
        Dynamisch schakelen met drie lagen intelligentie:
        1. Fase-snapshot vóór uitschakelen
        2. Mimicry-weging: lampen die bewoners op dit tijdstip zelf gebruiken,
           krijgen hogere kans om gekozen te worden
        3. Dynamische staptijd + bonus bij negatieve prijs
        """
        # Fase-snapshot VOOR uitschakelen
        if phase_currents and self._current_on:
            candidate = next(
                (l for l in self._lamps
                 if l.entity_id in self._current_on and l.detected_phase is None),
                None,
            )
            if candidate:
                self._probe_entity = candidate.entity_id
                self._probe_pre    = dict(phase_currents)
                self._probe_time   = time.time()

        # Huidige lampen uit
        for eid in list(self._current_on):
            await self._set_light(eid, False)
        self._current_on.clear()

        # ── Mimicry-gewogen selectie ───────────────────────────────────────
        # Bereken gewichten: basisgewicht 1.0 + mimicry-bonus
        weights = []
        for lamp in active_lamps:
            score = lamp.mimicry_score(hour, dow)
            # Boost: lampen die bewoners hier normaal gebruiken, eerder kiezen
            weights.append(1.0 + score * 3.0)

        # Aantal lampen: gewogen willekeurig 1-3
        max_n = min(MAX_LAMPS_ON, len(active_lamps))
        count_weights = [3.0, 1.5, 0.7][:max_n]
        n = random.choices(range(1, max_n + 1), weights=count_weights[:max_n])[0]

        # Kies n lampen gewogen op mimicry
        total_w = sum(weights)
        norm_w  = [w / total_w for w in weights]
        chosen: list[LampEntry] = []
        pool = list(zip(active_lamps, norm_w))
        random.shuffle(pool)
        pool.sort(key=lambda x: -x[1])   # hoogste kans eerst
        seen: set[str] = set()
        for lamp, w in pool:
            if len(chosen) >= n:
                break
            if lamp.entity_id not in seen:
                # Stochastisch accepteren: zelfs hoge-kans lampen soms niet nemen
                if random.random() < (w * 3 + 0.2):
                    chosen.append(lamp)
                    seen.add(lamp.entity_id)
        # Fallback als niet genoeg gekozen
        while len(chosen) < n:
            remaining = [l for l in active_lamps if l.entity_id not in seen]
            if not remaining:
                break
            extra = random.choice(remaining)
            chosen.append(extra)
            seen.add(extra.entity_id)

        for lamp in chosen:
            await self._set_light(lamp.entity_id, True)
            self._current_on.add(lamp.entity_id)

        # ── Dynamische staptijd ────────────────────────────────────────────
        mu    = (MIN_STEP_S + MAX_STEP_S) / 2
        sigma = (MAX_STEP_S - MIN_STEP_S) / 4
        step  = int(max(MIN_STEP_S, min(MAX_STEP_S, random.gauss(mu, sigma))))

        # Negatieve prijs → langere circulatie (gratis energie, max beveiliging)
        if self._neg_price_active:
            step += NEG_PRICE_STEP_BONUS_S
            _LOGGER.debug("LampCirculation: negatieve prijs → step verlengd naar %ds", step)

        self._next_switch = time.time() + step

        mimicry_labels = [l.label for l in chosen if l.mimicry_score(hour, dow) > 0.3]
        _LOGGER.info(
            "LampCirculation: %d lamp(en) aan [%s]%s, over %ds",
            n,
            ", ".join(l.label for l in chosen),
            f" (mimicry: {mimicry_labels})" if mimicry_labels else "",
            step,
        )

    # ── Seizoensintelligentie: zon-gebaseerde nacht ───────────────────────────

    def _is_sun_night(self, hour: int) -> bool:
        """
        Bepaal nacht op basis van sun.sun entity in HA.
        Circulatie start SUN_OFFSET_MIN minuten NA zonsondergang.
        Als sun.sun niet beschikbaar: fallback op geconfigureerde tijden.
        """
        try:
            sun_state = self.hass.states.get("sun.sun")
            if not sun_state:
                return False

            if sun_state.state == "below_horizon":
                # Check of we al SUN_OFFSET_MIN na zonsondergang zijn
                next_rising_raw = sun_state.attributes.get("next_rising")
                next_setting_raw = sun_state.attributes.get("next_setting")
                if next_rising_raw:
                    # Zon is onder — het is nacht (na offset)
                    # Bepaal of het vroeg-nacht is (net na ondergang) of laat-nacht
                    # We gebruiken de elevatie: onder -3° = echt donker
                    elevation = float(sun_state.attributes.get("elevation", -90))
                    return elevation < -3.0
                return True  # zon onder, geen verdere info
            return False  # zon boven horizon: geen nacht
        except Exception:
            return False

    def _sun_set_offset_active(self) -> bool:
        """True als we binnen SUN_OFFSET_MIN na zonsondergang zitten (wacht-periode)."""
        try:
            sun_state = self.hass.states.get("sun.sun")
            if not sun_state or sun_state.state != "below_horizon":
                return False
            elevation = float(sun_state.attributes.get("elevation", -90))
            # Elevation net onder 0: nog geen SUN_OFFSET_MIN verstreken
            return -3.0 < elevation < 0.0
        except Exception:
            return False

    # ── Leerpatroon: bewonersgedrag vanuit HA states ──────────────────────────

    def _learn_from_ha_states(self, hour: int, dow: int) -> None:
        """
        Leer van het echte bewonersgedrag: als een lamp nu aan is in HA
        terwijl de AbsenceDetector 'home' zegt, registreer dat als normaal
        gebruik-patroon voor dit tijdstip.
        """
        for lamp in self._lamps:
            if lamp.excluded:
                continue
            state = self.hass.states.get(lamp.entity_id)
            if state and state.state in ("on", "playing"):
                lamp.learn_on(hour, dow)

    def _update_pir_states(self, now: float) -> None:
        """Lees PIR-sensoren en update last_active timestamps."""
        for lamp in self._lamps:
            if not lamp.pir_entity:
                continue
            pir_state = self.hass.states.get(lamp.pir_entity)
            if pir_state and pir_state.state in ("on", "detected", "motion"):
                lamp._pir_last_active = now

    # ── Fase-detectie bijvangst ───────────────────────────────────────────────

    def _finalize_phase_probe(self, current_currents: dict) -> None:
        eid = self._probe_entity
        self._probe_entity = None

        lamp = next((l for l in self._lamps if l.entity_id == eid), None)
        if lamp is None or lamp.detected_phase is not None:
            return

        deltas: dict[str, float] = {}
        for ph in ("L1", "L2", "L3"):
            pre = self._probe_pre.get(ph)
            cur = current_currents.get(ph)
            if pre is not None and cur is not None:
                deltas[ph] = pre - cur

        if not deltas:
            return

        winner = max(deltas, key=lambda p: deltas[p])
        delta  = deltas[winner]
        total  = sum(abs(v) for v in deltas.values())

        if delta < PHASE_MIN_DELTA_A or total == 0:
            return

        confidence = delta / total
        lamp.detected_phase   = winner
        lamp.phase_confidence = round(confidence, 2)
        estimated_power_w     = round(delta * 230.0, 1)
        lamp.nilm_power_w     = estimated_power_w

        self._last_phase_tip = (
            f"⚡ Nieuw: '{lamp.label}' → fase {winner} "
            f"({confidence*100:.0f}% zekerheid, ~{estimated_power_w:.0f}W)"
        )

        _LOGGER.info(
            "LampCirculation fase-bijvangst: '%s' → %s (%.0f%%, ~%.0fW)",
            lamp.label, winner, confidence * 100, estimated_power_w,
        )

        if self._nilm_register_cb:
            try:
                self._nilm_register_cb(eid, "light", estimated_power_w)
            except Exception as e:
                _LOGGER.debug("LampCirculation NILM callback fout: %s", e)

    # ── Lamp bediening ────────────────────────────────────────────────────────

    async def _turn_all_off(self) -> None:
        for eid in list(self._current_on):
            await self._set_light(eid, False)
        self._current_on.clear()

    async def _set_light(self, entity_id: str, on: bool) -> None:
        domain  = entity_id.split(".")[0]
        service = "turn_on" if on else "turn_off"
        try:
            await self.hass.services.async_call(
                domain, service, {"entity_id": entity_id}, blocking=False,
            )
        except Exception as err:
            _LOGGER.warning("LampCirculation: '%s' fout: %s", entity_id, err)

    # ── Status factory ────────────────────────────────────────────────────────

    def _status(
        self,
        active: bool, mode: str, reason: str,
        occupancy_state: str, occupancy_confidence: float,
        lamps_on: list            = None,
        lamps_on_labels: list     = None,
        next_switch_in_s: int     = 0,
        mimicry_active: bool      = False,
    ) -> CirculationStatus:
        lamps_on        = lamps_on or []
        lamps_on_labels = lamps_on_labels or []
        lamps_active    = sum(1 for l in self._lamps if not l.excluded)
        lamps_excluded  = sum(1 for l in self._lamps if l.excluded)
        lamps_with_phase = sum(1 for l in self._lamps if l.detected_phase)

        phase_tip = self._last_phase_tip
        unknown_count = sum(1 for l in self._lamps if not l.excluded and not l.detected_phase)
        if not phase_tip and unknown_count > 0:
            phase_tip = (
                f"💡 Tip: {unknown_count} lamp(en) zonder bekende fase. "
                f"Start de test om fase-detectie te triggeren."
            )

        neg_bonus = f" (+{NEG_PRICE_STEP_BONUS_S//60}min negatieve prijs)" if self._neg_price_active else ""
        if mode == "circulation":
            advice = f"🔒 Beveiliging actief — {len(lamps_on)} lamp(en) aan{neg_bonus}."
        elif mode == "test":
            advice = f"🔬 Testmodus — {len(lamps_on)} lamp(en) aan, nog {next_switch_in_s}s."
        elif mode == "night_off":
            advice = "🌙 Nachtmodus — alles uit."
        elif mode == "energy_saving":
            advice = "⚡ Wacht op bevestiging afwezigheid..."
        elif not self._enabled:
            advice = "ℹ️ Uitgeschakeld."
        else:
            advice = "✅ Standby — niemand weg."

        return CirculationStatus(
            enabled              = self._enabled,
            active               = active,
            test_mode            = self._test_active,
            mode                 = mode,
            reason               = reason,
            lamps_on             = lamps_on,
            lamps_on_labels      = lamps_on_labels,
            next_switch_in_s     = next_switch_in_s,
            lamps_registered     = len(self._lamps),
            lamps_active         = lamps_active,
            lamps_excluded       = lamps_excluded,
            lamps_with_phase     = lamps_with_phase,
            occupancy_state      = occupancy_state,
            occupancy_confidence = occupancy_confidence,
            advice               = advice,
            phase_tip            = phase_tip,
            mimicry_active       = mimicry_active,
            neg_price_active     = self._neg_price_active,
            sun_derived_night    = self._sun_derived_night,
            lamp_phases          = [
                {
                    "entity_id":  l.entity_id,
                    "label":      l.label,
                    "excluded":   l.excluded,
                    "pir":        l.pir_entity,
                    "phase":      l.detected_phase,
                    "confidence": l.phase_confidence,
                    "power_w":    l.nilm_power_w,
                    "mimicry":    round(
                        l.mimicry_score(datetime.now().hour, datetime.now().weekday()), 2
                    ),
                }
                for l in self._lamps
            ],
        )

    def get_status_dict(self, status: CirculationStatus) -> dict:
        return {
            "enabled":              status.enabled,
            "active":               status.active,
            "test_mode":            status.test_mode,
            "mode":                 status.mode,
            "reason":               status.reason,
            "lamps_on":             status.lamps_on,
            "lamps_on_labels":      status.lamps_on_labels,
            "next_switch_in_s":     status.next_switch_in_s,
            "lamps_registered":     status.lamps_registered,
            "lamps_active":         status.lamps_active,
            "lamps_excluded":       status.lamps_excluded,
            "lamps_with_phase":     status.lamps_with_phase,
            "occupancy_state":      status.occupancy_state,
            "occupancy_confidence": status.occupancy_confidence,
            "advice":               status.advice,
            "phase_tip":            status.phase_tip,
            "mimicry_active":       status.mimicry_active,
            "neg_price_active":     status.neg_price_active,
            "sun_derived_night":    status.sun_derived_night,
            "lamp_phases":          status.lamp_phases,
        }


# ── Ghost 2.0 — TV Simulator ──────────────────────────────────────────────────

class GhostTVSimulator:
    """Simuleert het flikkerende licht van een televisie via een RGB lamp.

    Werkt alleen als het huis in Away-mode staat.
    Simuleert scene-wisselingen op basis van gemiddelde TV-kijkpatronen:
    - Elke 3-8 seconden: kleine kleur/helderheidswissel (scene change)
    - Elke 20-120 seconden: grotere wissel (kanaalwisseling of commercial)
    - Pauzeert automatisch tussen 02:00 en 06:00 (niemand kijkt TV)
    - Stopt zodra huis niet meer Away is

    Configuratie:
      entity_id    str   — RGB lamp in de woonkamer
      active       bool  — module in/uitschakelen
      night_pause_start_h  int  — uur om te pauzeren (default 2)
      night_pause_end_h    int  — uur om te hervatten (default 6)
    """

    # TV-achtige kleurtemperaturen (RGB waarden, warm blauw-grijs van LCD schermen)
    _TV_COLORS = [
        (120, 140, 180),  # koud blauw (actiefilm)
        (180, 160, 120),  # warm geel (documentaire)
        ( 80, 120, 160),  # donkerblauw (nachtscène)
        (200, 190, 160),  # neutraal wit (nieuws)
        (160,  80,  60),  # rood-oranje (explosie)
        ( 60, 100, 140),  # donker (thriller)
        (180, 170, 150),  # licht grijs (talkshow)
        (100, 140, 100),  # groen (natuur)
    ]

    def __init__(self, hass, entity_id: str, active: bool = True,
                 night_pause_start_h: int = 2, night_pause_end_h: int = 6) -> None:
        self._hass     = hass
        self._entity   = entity_id
        self._active   = active
        self._night_start = night_pause_start_h
        self._night_end   = night_pause_end_h
        self._running  = False
        self._next_small_change = 0.0   # kleine scene-wissel
        self._next_big_change   = 0.0   # grote scene-wissel
        self._current_color     = (120, 140, 180)
        self._current_brightness = 120

    def _is_night_pause(self) -> bool:
        h = datetime.now().hour
        if self._night_start > self._night_end:
            return h >= self._night_start or h < self._night_end
        return self._night_start <= h < self._night_end

    async def _set_rgb(self, r: int, g: int, b: int, brightness: int) -> None:
        try:
            await self._hass.services.async_call(
                "light", "turn_on",
                {
                    "entity_id":  self._entity,
                    "rgb_color":  [r, g, b],
                    "brightness": max(10, min(255, brightness)),
                    "transition": random.uniform(0.3, 1.5),
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.debug("GhostTVSim: set_rgb fout: %s", e)

    async def _turn_off(self) -> None:
        try:
            await self._hass.services.async_call(
                "light", "turn_off",
                {"entity_id": self._entity, "transition": 2},
                blocking=False,
            )
        except Exception as e:
            _LOGGER.debug("GhostTVSim: turn_off fout: %s", e)

    async def tick(self, is_away: bool) -> str:
        """Aanroepen elke coordinator tick. Returns: actieve modus string."""
        if not self._active or not self._entity:
            return "disabled"

        now = time.time()

        # Niet Away of nachtpauze → lamp uit
        if not is_away or self._is_night_pause():
            if self._running:
                self._running = False
                await self._turn_off()
                _LOGGER.debug("GhostTVSim: gestopt (%s)", "nachtpauze" if self._is_night_pause() else "thuis")
            return "off"

        # Away mode actief → TV simuleren
        if not self._running:
            self._running = True
            self._next_small_change = now + random.uniform(3, 8)
            self._next_big_change   = now + random.uniform(20, 60)
            _LOGGER.info("GhostTVSim: TV simulatie gestart op %s", self._entity)

        # Kleine scene-wissel (elke 3-8s): kleine helderheidswijziging
        if now >= self._next_small_change:
            r, g, b = self._current_color
            # Kleine variatie ±15 per kanaal
            r2 = max(10, min(255, r + random.randint(-15, 15)))
            g2 = max(10, min(255, g + random.randint(-15, 15)))
            b2 = max(10, min(255, b + random.randint(-15, 15)))
            bri = max(30, min(200, self._current_brightness + random.randint(-20, 20)))
            await self._set_rgb(r2, g2, b2, bri)
            self._current_brightness = bri
            self._next_small_change = now + random.uniform(3, 8)

        # Grote scene-wissel (elke 20-120s): nieuwe kleur (kanaalwisseling)
        if now >= self._next_big_change:
            self._current_color = random.choice(self._TV_COLORS)
            r, g, b = self._current_color
            # Bij grote wissel soms even zwart (reclame/einde scène)
            if random.random() < 0.2:
                await self._turn_off()
                self._next_small_change = now + random.uniform(1, 3)
            else:
                bri = random.randint(60, 180)
                await self._set_rgb(r, g, b, bri)
                self._current_brightness = bri
            self._next_big_change = now + random.uniform(20, 120)

        return "simulating"

    def get_status(self) -> dict:
        return {
            "entity_id": self._entity,
            "active":    self._active,
            "running":   self._running,
            "mode":      "simulating" if self._running else "off",
        }


# ── Ghost 2.0 — Audio Deterrence ─────────────────────────────────────────────

class GhostAudioDeterrence:
    """Speelt huiselijke geluiden af via media_player bij bewegingsdetectie in Away mode.

    Werkt samen met GhostTVSimulator:
    - Als huis Away is en een bewegingssensor triggert → speel afschrikkend geluid
    - Geluiden: hond blaft, vaatwasser, TV-geluid, stemmen
    - Cooldown na elke trigger (5 min) om herhaling te voorkomen
    - Nachtpauze configureerbaar

    Configuratie:
      media_player     str        — media_player entity voor geluidsweergave
      motion_sensors   list[str]  — binary_sensor.* bewegingssensoren bij de deur
      sounds           list[str]  — URLs of media-content IDs
      volume           float      — volume 0.0-1.0 (default 0.4)
      cooldown_s       int        — seconden tussen triggers (default 300)
      active           bool
      night_pause_start_h  int    — uur pauzeren (default 23)
      night_pause_end_h    int    — uur hervatten (default 6)
    """

    # Standaard geluiden — overschrijfbaar via configuratie
    DEFAULT_SOUNDS = [
        "media-source://media_source/local/cloudems/sounds/dog_bark.mp3",
        "media-source://media_source/local/cloudems/sounds/dishwasher.mp3",
        "media-source://media_source/local/cloudems/sounds/voices_background.mp3",
    ]

    def __init__(
        self,
        hass,
        media_player: str,
        motion_sensors: list,
        sounds: list        = None,
        volume: float       = 0.4,
        cooldown_s: int     = 300,
        active: bool        = True,
        night_pause_start_h: int = 23,
        night_pause_end_h: int   = 6,
    ) -> None:
        self._hass          = hass
        self._player        = media_player
        self._sensors       = motion_sensors or []
        self._sounds        = sounds or self.DEFAULT_SOUNDS
        self._volume        = max(0.0, min(1.0, volume))
        self._cooldown_s    = cooldown_s
        self._active        = active
        self._night_start   = night_pause_start_h
        self._night_end     = night_pause_end_h
        self._last_trigger  = 0.0
        self._trigger_count = 0

    def _is_night_pause(self) -> bool:
        h = datetime.now().hour
        if self._night_start > self._night_end:
            return h >= self._night_start or h < self._night_end
        return self._night_start <= h < self._night_end

    def _motion_detected(self) -> bool:
        """Check of een van de bewegingssensoren actief is."""
        for eid in self._sensors:
            state = self._hass.states.get(eid)
            if state and state.state == "on":
                return True
        return False

    async def _play_sound(self, sound_url: str) -> None:
        try:
            await self._hass.services.async_call(
                "media_player", "play_media",
                {
                    "entity_id":   self._player,
                    "media_content_id":   sound_url,
                    "media_content_type": "music",
                },
                blocking=False,
            )
            await self._hass.services.async_call(
                "media_player", "volume_set",
                {"entity_id": self._player, "volume_level": self._volume},
                blocking=False,
            )
        except Exception as e:
            _LOGGER.debug("GhostAudio: play fout: %s", e)

    async def tick(self, is_away: bool) -> str:
        """Aanroepen elke coordinator tick. Returns: status string."""
        if not self._active or not self._player or not self._sensors:
            return "disabled"

        if not is_away:
            return "home"

        if self._is_night_pause():
            return "night_pause"

        now = time.time()

        # Cooldown check
        if now - self._last_trigger < self._cooldown_s:
            return "cooldown"

        # Beweging gedetecteerd?
        if not self._motion_detected():
            return "watching"

        # Trigger — kies willekeurig geluid
        sound = random.choice(self._sounds)
        await self._play_sound(sound)
        self._last_trigger = now
        self._trigger_count += 1

        _LOGGER.info(
            "GhostAudio: beweging gedetecteerd — %s afgespeeld (trigger #%d)",
            sound.split("/")[-1], self._trigger_count
        )
        return "triggered"

    def get_status(self) -> dict:
        cooldown_left = max(0, int(self._cooldown_s - (time.time() - self._last_trigger)))
        return {
            "active":         self._active,
            "media_player":   self._player,
            "sensors":        self._sensors,
            "trigger_count":  self._trigger_count,
            "cooldown_left_s": cooldown_left,
            "last_trigger_ts": self._last_trigger,
        }
