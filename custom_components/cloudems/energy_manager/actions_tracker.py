# -*- coding: utf-8 -*-
"""
CloudEMS — "Wat heeft CloudEMS vandaag voor je gedaan?" — v1.0.0

Compacte dagkaart met directe waarde-communicatie:
  "Vandaag €1.23 bespaard — boiler 2u verschoven,
   EV op PV-surplus geladen, 1 congestie-event afgevangen."

Bijhouden van CloudEMS-acties gedurende de dag:
  • Elke action die de coordinator uitvoert, wordt hier geregistreerd
  • Om middernacht wordt de dagkaart gereset en de vorige dag opgeslagen
  • Sensor: cloudems_dag_acties

Actietypes (geregistreerd door coordinator via log_action()):
  boiler_shifted       — boiler verschoven naar goedkoper uur
  ev_solar             — EV geladen op PV-surplus (kWh)
  ev_cheap             — EV geladen op goedkoopste uren (kWh)
  battery_arbitrage    — batterij gepland op EPEX-spread
  shutter_thermal      — rolluik geopend/gesloten voor thermische winst
  congestion_shed      — last afgeworpen tijdens congestie
  peak_shed            — last afgeworpen voor piek-preventie
  cheap_switch         — switch geactiveerd tijdens goedkoopste uren
  solar_curtail        — PV teruggeregeld om fasegrens te beschermen
  preheat_scheduled    — voorverwarming verschoven naar goedkoop uur

Elke actie heeft:
  category:   boiler / ev / battery / shutter / grid / switch / climate
  description: leesbare tekst
  saving_eur:  geschatte besparing (kan 0 zijn bij veiligheidsacties)
  kwh:         eventueel verschoven/bespaard vermogen

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Maximaal aantal acties per dag bijhouden
MAX_ACTIONS_PER_DAY = 200


@dataclass
class DayAction:
    """Eén CloudEMS-actie gedurende de dag."""
    ts:          float
    action_type: str
    category:    str
    description: str
    saving_eur:  float = 0.0
    kwh:         float = 0.0

    def to_dict(self) -> dict:
        return {
            "time":        datetime.fromtimestamp(self.ts, tz=timezone.utc).strftime("%H:%M"),
            "type":        self.action_type,
            "category":    self.category,
            "description": self.description,
            "saving_eur":  round(self.saving_eur, 3),
            "kwh":         round(self.kwh, 3),
        }


@dataclass
class DaySummaryCard:
    """Dagkaart — wat heeft CloudEMS vandaag gedaan?"""
    date:              str
    total_saving_eur:  float
    total_kwh:         float
    actions:           list[DayAction] = field(default_factory=list)
    congestion_events: int = 0
    peak_events:       int = 0
    headline:          str = ""

    def build_headline(self) -> str:
        """Maak een leesbare samenvatting van de dag."""
        parts = []

        saving = self.total_saving_eur
        if saving >= 0.05:
            parts.append(f"€{saving:.2f} bespaard")

        # Categoriseer acties
        cats: dict[str, list[DayAction]] = {}
        for a in self.actions:
            cats.setdefault(a.category, []).append(a)

        if "ev" in cats:
            kwh = sum(a.kwh for a in cats["ev"])
            if kwh > 0.1:
                parts.append(f"EV {kwh:.1f} kWh smart geladen")

        if "boiler" in cats:
            n = len([a for a in cats["boiler"] if "verschov" in a.description.lower()])
            if n:
                parts.append(f"boiler {n}× verschoven")

        if self.congestion_events:
            parts.append(f"{self.congestion_events} congestie-event{'s' if self.congestion_events > 1 else ''} afgevangen")

        if self.peak_events:
            parts.append(f"{self.peak_events} piekmeter-actie{'s' if self.peak_events > 1 else ''}")

        if "battery" in cats:
            batt_saving = sum(a.saving_eur for a in cats["battery"])
            if batt_saving >= 0.05:
                parts.append(f"batterij €{batt_saving:.2f} arbitrage")

        if not parts:
            return "Geen significante acties vandaag"

        return " — ".join(parts)

    def to_dict(self) -> dict:
        return {
            "date":             self.date,
            "headline":         self.headline or self.build_headline(),
            "total_saving_eur": round(self.total_saving_eur, 2),
            "total_kwh":        round(self.total_kwh, 2),
            "congestion_events": self.congestion_events,
            "peak_events":       self.peak_events,
            "action_count":      len(self.actions),
            "actions_by_category": {
                cat: len(acts)
                for cat, acts in {
                    c: [a for a in self.actions if a.category == c]
                    for c in {a.category for a in self.actions}
                }.items()
            },
            "recent_actions": [a.to_dict() for a in self.actions[-10:]],
        }


# ── Hoofd-klasse ──────────────────────────────────────────────────────────────

class CloudEMSActionsTracker:
    """
    Houdt bij welke acties CloudEMS vandaag heeft ondernomen.

    Gebruik in coordinator:
        self._actions_tracker = CloudEMSActionsTracker()

        # Bij elke actie:
        self._actions_tracker.log_action(
            action_type="boiler_shifted",
            category="boiler",
            description="Boiler verschoven van 09:00 naar 02:00 (cheapest uur)",
            saving_eur=0.18,
        )

        # In coordinator data:
        data["dag_acties"] = self._actions_tracker.get_card().to_dict()
    """

    def __init__(self) -> None:
        self._today_str: str             = ""
        self._today_actions: list[DayAction] = []
        self._yesterday_card: Optional[DaySummaryCard] = None

    def log_action(
        self,
        action_type: str,
        category: str,
        description: str,
        saving_eur: float = 0.0,
        kwh: float = 0.0,
    ) -> None:
        """Registreer een CloudEMS-actie."""
        self._maybe_reset()

        if len(self._today_actions) >= MAX_ACTIONS_PER_DAY:
            return

        action = DayAction(
            ts          = time.time(),
            action_type = action_type,
            category    = category,
            description = description,
            saving_eur  = saving_eur,
            kwh         = kwh,
        )
        self._today_actions.append(action)
        _LOGGER.debug("CloudEMS actie: [%s] %s (€%.3f)", category, description, saving_eur)

    def get_card(self) -> DaySummaryCard:
        """Huidige dagkaart."""
        self._maybe_reset()
        card = self._build_card(self._today_str, self._today_actions)
        card.headline = card.build_headline()
        return card

    def get_yesterday_card(self) -> Optional[DaySummaryCard]:
        """Gisterenkaart."""
        return self._yesterday_card

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _maybe_reset(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._today_str:
            if self._today_str and self._today_actions:
                self._yesterday_card = self._build_card(self._today_str, self._today_actions)
                self._yesterday_card.headline = self._yesterday_card.build_headline()
            self._today_str    = today
            self._today_actions = []

    @staticmethod
    def _build_card(date: str, actions: list[DayAction]) -> DaySummaryCard:
        total_saving = sum(a.saving_eur for a in actions)
        total_kwh    = sum(a.kwh for a in actions)
        congestion   = sum(1 for a in actions if a.action_type == "congestion_shed")
        peak         = sum(1 for a in actions if a.action_type == "peak_shed")
        return DaySummaryCard(
            date              = date,
            total_saving_eur  = total_saving,
            total_kwh         = total_kwh,
            actions           = list(actions),
            congestion_events = congestion,
            peak_events       = peak,
        )


# ── Actie-constanten voor gebruik in coordinator ──────────────────────────────

class Actions:
    """Constanten voor actietypes — voorkomt typo's."""
    BOILER_SHIFTED     = "boiler_shifted"
    EV_SOLAR           = "ev_solar"
    EV_CHEAP           = "ev_cheap"
    BATTERY_ARBITRAGE  = "battery_arbitrage"
    SHUTTER_THERMAL    = "shutter_thermal"
    CONGESTION_SHED    = "congestion_shed"
    PEAK_SHED          = "peak_shed"
    CHEAP_SWITCH       = "cheap_switch"
    SOLAR_CURTAIL      = "solar_curtail"
    PREHEAT_SCHEDULED  = "preheat_scheduled"

    # Categorieën
    CAT_BOILER    = "boiler"
    CAT_EV        = "ev"
    CAT_BATTERY   = "battery"
    CAT_SHUTTER   = "shutter"
    CAT_GRID      = "grid"
    CAT_SWITCH    = "switch"
    CAT_CLIMATE   = "climate"
    CAT_SOLAR     = "solar"
