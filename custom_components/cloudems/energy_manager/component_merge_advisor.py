# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Component Merge Advisor — v1.0.0

Detecteert wanneer ApplianceHMM meerdere sub-componenten van hetzelfde
fysieke apparaat heeft geïdentificeerd (bijv. wasmachine motor + verwarmingselement)
en suggereert samenvoegen via een HA persistent_notification.

Inspiratie: Sense vraagt gebruikers expliciet om "Motor 2" en "Heat 3" samen
te voegen tot "Wasmachine". CloudEMS heeft de HMM die dit intern al doet voor
de energieberekening, maar communiceerde nooit naar de gebruiker WELKE
sub-componenten herkend zijn.

Werking:
  1. HMM produceert actieve sessies: [{device_type, phase, states, energy_kwh}]
  2. Als twee sessies op dezelfde fase tegelijk actief zijn én beide passen
     bij hetzelfde apparaat-type (bijv. washing_machine_motor +
     washing_machine_heat → "wasmachine") → merge-suggestie
  3. Suggestie wordt gecombineerd in één HA-notificatie met uitleg
  4. Cooldown per apparaat-combinatie: 7 dagen

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# Apparaattypen die uit meerdere HMM-componenten bestaan
# key = overkoepelend type, value = sub-types die bij elkaar horen
MULTI_COMPONENT_APPLIANCES: Dict[str, List[str]] = {
    "washing_machine": ["washing_machine", "motor", "heat"],
    "dryer":           ["dryer", "motor", "heat"],
    "dishwasher":      ["dishwasher", "motor", "heat"],
    "oven":            ["oven", "heat"],
    "heat_pump":       ["heat_pump", "motor", "heat"],
    "ev_charger":      ["ev_charger", "motor"],
}

MERGE_COOLDOWN_S = 604_800   # 7 dagen per combinatie

# Mooie namen voor de gebruiker
APPLIANCE_LABELS = {
    "washing_machine": "Wasmachine",
    "dryer":           "Droger",
    "dishwasher":      "Vaatwasser",
    "oven":            "Oven",
    "heat_pump":       "Warmtepomp",
    "ev_charger":      "Laadpaal",
}

COMPONENT_LABELS = {
    "motor": "motor",
    "heat":  "verwarmingselement",
}


class ComponentMergeAdvisor:
    """
    Analyseert HMM-sessies en suggereert component-samenvoegingen.

    Gebruik in coordinator._async_update_data():
        self._merge_advisor.check(
            hmm_sessions = self._hmm.get_active_sessions() if self._hmm else [],
            nilm_devices = nilm_devices_enriched,
        )
    """

    def __init__(self, hass) -> None:
        self._hass   = hass
        self._notified: Dict[str, float] = {}   # key → last_notified_ts

    def check(
        self,
        hmm_sessions: List[dict],
        nilm_devices: List[dict],
    ) -> None:
        """Analyseer actieve HMM-sessies op samenvoeg-kansen."""
        if not hmm_sessions:
            return

        # Groepeer actieve sessies op fase
        by_phase: Dict[str, List[dict]] = {}
        for s in hmm_sessions:
            if s.get("is_closed"):
                continue
            phase = s.get("phase", "L1")
            by_phase.setdefault(phase, []).append(s)

        for phase, sessions in by_phase.items():
            self._check_phase(phase, sessions, nilm_devices)

    def _check_phase(
        self,
        phase: str,
        sessions: List[dict],
        nilm_devices: List[dict],
    ) -> None:
        types_on = {s.get("device_type", ""): s for s in sessions}

        for appliance, components in MULTI_COMPONENT_APPLIANCES.items():
            # Hoeveel componenten van dit apparaat zijn gelijktijdig actief?
            active_comps = [c for c in components if c in types_on]
            if len(active_comps) < 2:
                continue

            key = f"{appliance}_{phase}"
            now = time.time()
            if now - self._notified.get(key, 0) < MERGE_COOLDOWN_S:
                continue

            # Controleer of de NILM al een bevestigd apparaat heeft
            # voor dit type op deze fase — dan is samenvoegen niet nodig
            already_confirmed = any(
                d.get("device_type") == appliance
                and d.get("confirmed")
                and d.get("phase", "L1") == phase
                for d in nilm_devices
            )
            if already_confirmed:
                continue

            # Bereken totaal vermogen van de sessies
            total_w = sum(
                float(sessions[0].get("current_power_w", 0) if sessions else 0)
                for s in sessions if s.get("device_type") in active_comps
            )

            self._send_merge_notification(appliance, phase, active_comps, total_w)
            self._notified[key] = now

    def _send_merge_notification(
        self,
        appliance:   str,
        phase:       str,
        components:  List[str],
        total_w:     float,
    ) -> None:
        label     = APPLIANCE_LABELS.get(appliance, appliance.replace("_", " ").title())
        comp_str  = " en ".join(COMPONENT_LABELS.get(c, c) for c in components)
        notif_id  = f"cloudems_merge_{appliance}_{phase}"
        title     = f"💡 CloudEMS — {label} gedeeltelijk herkend"
        msg = (
            f"CloudEMS heeft een **{comp_str}** op fase {phase} herkend die "
            f"tegelijk actief zijn (≈ {total_w:.0f}W totaal).\n\nDit zijn waarschijnlijk sub-componenten van uw **{label}**.\n\n**Tip:** Bevestig het apparaat als '{label}' in het CloudEMS dashboard. "
            f"CloudEMS leert dan het volledige verbruiksprofiel als één apparaat en trakt het correct af van het onbekende verbruik."
        )
        try:
            self._hass.components.persistent_notification.async_create(
                message         = msg,
                title           = title,
                notification_id = notif_id,
            )
            _LOGGER.info(
                "ComponentMergeAdvisor: %s op %s heeft %d componenten actief",
                appliance, phase, len(components),
            )
        except Exception as ex:
            _LOGGER.debug("ComponentMergeAdvisor notificatie fout: %s", ex)
