# -*- coding: utf-8 -*-
"""
CloudEMS — Verbeterde Installatiescore Dashboard Presentatie — v2.0.0

Uitbreiding op installation_score.py:
  1. Score prominenter aanwezig in het overzicht (niet alleen op Diagnose-tab)
  2. Per missend onderdeel: directe actieknop / HA-deeplink
  3. Score-trending over 7 dagen (al aanwezig in v1.0 Store, nu ook als sensor)
  4. "Quick wins" — top 3 verbeteringen gesorteerd op impact/moeite verhouding

Nieuwe sensor:
  sensor.cloudems_setup_score
    state:      score 0-100
    attributen:
      grade, grade_emoji, summary, quick_wins[],
      items[], trend_7d, next_step_label, next_step_url

Gebruik in coordinator:
    presenter = InstallationScorePresenter(score_result)
    data["setup_score"] = presenter.to_dashboard_dict()

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Action URLs voor quick-wins ───────────────────────────────────────────────
# HA deeplinks / documentatie-URLs per scorecriterium
ACTION_URLS: dict[str, str] = {
    "p1_sensor":        "/config/integrations",
    "phase_sensors":    "https://cloudems.eu/wiki/fase-sensoren",
    "pv_inverter":      "/config/integrations",
    "epex_pricing":     "https://cloudems.eu/wiki/epex",
    "ai_provider":      "https://cloudems.eu/wiki/nilm-ai",
    "ev_charger":       "/config/integrations",
    "battery":          "/config/integrations",
    "gas_sensor":       "/config/integrations",
    "tariff_config":    "/config/integrations/cloudems",
    "advanced":         "/config/integrations/cloudems",
}

# Impact/moeite matrix (hoger = hogere prioriteit voor quick-win)
IMPACT_EFFORT: dict[str, float] = {
    "p1_sensor":     10.0,   # hoog impact, laag moeite (vaak al aanwezig)
    "epex_pricing":   8.0,   # gratis, hoog impact
    "tariff_config":  7.0,   # 5 min config
    "phase_sensors":  6.0,   # gemiddeld moeite
    "pv_inverter":    5.5,   # afhankelijk van omvormer-merk
    "battery":        4.0,
    "ev_charger":     4.0,
    "ai_provider":    3.5,   # vereist Ollama of cloud-key
    "gas_sensor":     3.0,
    "advanced":       2.0,
}


@dataclass
class QuickWin:
    """Een concrete verbetering met actieknop."""
    key:          str
    label:        str
    tip:          str
    impact_pts:   int
    action_url:   str
    effort_label: str   # "5 minuten" / "nieuwe hardware" / etc.


class InstallationScorePresenter:
    """
    Presentatielaag voor InstallationScore.
    Maakt de score klaar voor het dashboard en de overzichtssensor.

    Gebruik:
        from .energy_manager.installation_score import calculate_installation_score
        score = calculate_installation_score(config, hass_data)
        presenter = InstallationScorePresenter(score, trend_scores=[82, 84, 85])
        data["setup_score"] = presenter.to_dashboard_dict()
    """

    def __init__(
        self,
        score_result,           # InstallationScore object
        trend_scores: Optional[list[float]] = None,   # laatste 7 dagscores
    ) -> None:
        self._score    = score_result
        self._trend    = trend_scores or []

    def get_quick_wins(self, top_n: int = 3) -> list[QuickWin]:
        """Top N verbeteringen gesorteerd op impact/moeite."""
        wins: list[QuickWin] = []

        for item in self._score.items:
            if item.status == "ok":
                continue  # al geconfigureerd

            effort_url    = ACTION_URLS.get(item.key, "https://cloudems.eu/wiki")
            impact_effort = IMPACT_EFFORT.get(item.key, 1.0)
            effort_label  = _effort_label(item.key)

            wins.append(QuickWin(
                key         = item.key,
                label       = item.label,
                tip         = item.tip,
                impact_pts  = item.max_pts - item.points,   # punten te winnen
                action_url  = effort_url,
                effort_label = effort_label,
            ))

        # Sorteer: meeste punten te winnen * impact_effort factor
        wins.sort(
            key=lambda w: w.impact_pts * IMPACT_EFFORT.get(w.key, 1.0),
            reverse=True,
        )
        return wins[:top_n]

    def get_trend_direction(self) -> str:
        """Trend t.o.v. 7 dagen geleden: 'stijgend' / 'stabiel' / 'dalend'."""
        if len(self._trend) < 2:
            return "stabiel"
        delta = self._score.score - self._trend[0]
        if delta > 3:
            return "stijgend"
        if delta < -3:
            return "dalend"
        return "stabiel"

    def to_dashboard_dict(self) -> dict:
        """Volledig dashboard-attribuut dict voor de sensor."""
        quick_wins  = self.get_quick_wins(3)
        trend_dir   = self.get_trend_direction()

        # Beste volgende stap
        next_step = quick_wins[0] if quick_wins else None

        return {
            "score":            self._score.score,
            "grade":            self._score.grade,
            "grade_emoji":      self._score.grade_emoji,
            "summary":          self._score.summary,
            "trend_direction":  trend_dir,
            "trend_scores_7d":  self._trend[-7:] if self._trend else [],
            "next_step_label":  next_step.label if next_step else "Alles geconfigureerd 🎉",
            "next_step_tip":    next_step.tip if next_step else "",
            "next_step_url":    next_step.action_url if next_step else "",
            "quick_wins": [
                {
                    "key":          w.key,
                    "label":        w.label,
                    "tip":          w.tip,
                    "impact_pts":   w.impact_pts,
                    "action_url":   w.action_url,
                    "effort":       w.effort_label,
                }
                for w in quick_wins
            ],
            "items": [
                {
                    "key":    i.key,
                    "label":  i.label,
                    "points": i.points,
                    "max":    i.max_pts,
                    "status": i.status,
                    "tip":    i.tip,
                }
                for i in self._score.items
            ],
        }

    def should_show_persistent_notification(self) -> bool:
        """Stuur persistent notification als score < 50."""
        return self._score.score < 50

    def get_notification_text(self) -> str:
        """Tekst voor de persistent notification bij lage score."""
        wins = self.get_quick_wins(2)
        parts = [
            f"CloudEMS installatiescore: {self._score.score}/100 ({self._score.grade})\n",
            "Top verbeteringen:",
        ]
        for w in wins:
            parts.append(f"  • {w.label}: {w.tip}")
        return "\n".join(parts)


def _effort_label(key: str) -> str:
    """Mensleesbare inspanningsindicatie per criterium."""
    effort_map = {
        "p1_sensor":     "Controleer bestaande integratie",
        "epex_pricing":  "5 min — gratis API-sleutel",
        "tariff_config": "5 min — tarieven invullen",
        "phase_sensors": "Hardware-installatie vereist",
        "pv_inverter":   "Omvormer-integratie toevoegen",
        "battery":       "Batterij-integratie toevoegen",
        "ev_charger":    "Laadpaal-integratie toevoegen",
        "ai_provider":   "Ollama installeren of cloud-key",
        "gas_sensor":    "Gas-sensor koppelen",
        "advanced":      "Geavanceerde modus inschakelen",
    }
    return effort_map.get(key, "Configuratie nodig")
