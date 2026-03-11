# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Installatie-kwaliteitsscore — v1.0.0

Berekent een score van 0–100 voor de kwaliteit van de CloudEMS-installatie.
Hoe meer sensoren en functies geconfigureerd zijn, hoe hoger de score.

Score-opbouw:
  Categorie               Max   Gewicht
  ─────────────────────────────────────
  P1-lezer / netmeter     20    Fundament: zonder dit geen NILM
  Fase-sensoren           15    3-fase balans + per-fase NILM
  PV-omvormer             15    Zelfverbruik, teruglevering
  Energieprijzen (EPEX)   10    Slimme planning
  AI-provider             10    Betere classificatie
  EV-lader                 8    EV-planning
  Thuisbatterij            8    Batterij-optimalisatie
  Gas-sensor               5    Gasanalyse
  Tariefinstelling         5    Kostenberekening
  Overig (warmtepomp, …)   4    Geavanceerde features
  ─────────────────────────────────────
  Totaal                 100

Grade-systeem:
  A  90–100   Maximale configuratie
  B  70– 89   Goede configuratie
  C  50– 69   Basisfunctionaliteit
  D   0– 49   Minimale configuratie

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

_LOGGER = logging.getLogger(__name__)

# Const duplicaten (vermijd circulaire import)
_AI_PROVIDER_NONE = "none"


@dataclass
class ScoreItem:
    """Eén scorecriterium met status en advies."""
    key:       str
    label:     str
    points:    int         # behaalde punten
    max_pts:   int         # maximale punten voor dit criterium
    status:    str         # "ok" | "partial" | "missing"
    tip:       str = ""    # advies als status != "ok"


@dataclass
class InstallationScore:
    """Resultaat van de score-berekening."""
    score:   int             # 0–100
    grade:   str             # A / B / C / D
    items:   List[ScoreItem] = field(default_factory=list)
    summary: str = ""

    @property
    def grade_emoji(self) -> str:
        return {"A": "🏆", "B": "✅", "C": "⚠️", "D": "❌"}.get(self.grade, "❓")

    def to_dict(self) -> dict:
        return {
            "score":   self.score,
            "grade":   self.grade,
            "emoji":   self.grade_emoji,
            "summary": self.summary,
            "items": [
                {
                    "key":    i.key,
                    "label":  i.label,
                    "points": i.points,
                    "max":    i.max_pts,
                    "status": i.status,
                    "tip":    i.tip,
                }
                for i in self.items
            ],
        }


class InstallationScoreCalculator:
    """
    Berekent de installatie-kwaliteitsscore op basis van de CloudEMS-configuratie.

    Gebruik:
        calc = InstallationScoreCalculator(config)
        result = calc.calculate()
        # result.score  → 0-100
        # result.grade  → A/B/C/D
        # result.items  → lijst van ScoreItem met advies
    """

    _STORE_KEY  = "cloudems_installation_score_trend_v1"
    _TREND_DAYS = 7     # rolling window voor trend
    _DROP_ALERT = 5     # punten daling voor notificatie

    def __init__(self, config: dict) -> None:
        self._cfg    = config
        self._store  = None
        self._trend: list[dict] = []   # [{date, score}]
        self._dirty  = False
        self._last_save = 0.0

    async def async_setup(self, hass) -> None:
        """Laad score-trend na herstart."""
        import time as _t
        from homeassistant.helpers.storage import Store
        self._store = Store(hass, 1, self._STORE_KEY)
        try:
            data = await self._store.async_load() or {}
            self._trend = data.get("trend", [])
            _LOGGER.debug("InstallationScoreCalculator: %d trend-punten geladen", len(self._trend))
        except Exception as exc:
            _LOGGER.warning("InstallationScoreCalculator: laden mislukt: %s", exc)

    async def async_maybe_save(self) -> None:
        import time as _t
        if not self._store or not self._dirty:
            return
        if _t.time() - self._last_save < 3600:   # max 1× per uur opslaan
            return
        try:
            await self._store.async_save({"trend": self._trend[-self._TREND_DAYS * 2:]})
            self._dirty     = False
            self._last_save = _t.time()
        except Exception as exc:
            _LOGGER.warning("InstallationScoreCalculator: opslaan mislukt: %s", exc)

    def get_trend_alert(self) -> str | None:
        """Geeft waarschuwingstekst als score > _DROP_ALERT punten daalde in _TREND_DAYS dagen."""
        if len(self._trend) < 2:
            return None
        oldest = self._trend[0]["score"]
        newest = self._trend[-1]["score"]
        drop = oldest - newest
        if drop >= self._DROP_ALERT:
            return (
                f"CloudEMS installatie-score daalde {drop} punten in {len(self._trend)} dag(en) "
                f"({oldest} → {newest}). Mogelijk is een sensor offline gegaan."
            )
        return None

    def calculate(self) -> InstallationScore:
        items: List[ScoreItem] = []

        cfg = self._cfg

        # ── 1. P1-lezer / netmeter (20 pt) ───────────────────────────────────
        has_p1      = bool(cfg.get("p1_enabled") and (
            cfg.get("p1_host") or cfg.get("p1_serial_port") or cfg.get("p1_sensor")
        ))
        has_grid    = bool(cfg.get("grid_sensor"))
        has_sep_ie  = bool(cfg.get("use_separate_ie") and cfg.get("import_sensor") and cfg.get("export_sensor"))

        if has_p1:
            items.append(ScoreItem("p1", "P1-lezer", 20, 20, "ok"))
        elif has_sep_ie:
            items.append(ScoreItem("p1", "Import/export sensoren", 15, 20, "partial",
                "Tip: P1-lezer geeft hogere nauwkeurigheid dan losse sensoren."))
        elif has_grid:
            items.append(ScoreItem("p1", "Netmeter sensor", 10, 20, "partial",
                "Tip: Voeg een P1-lezer toe voor echte import/export meting en gasverbruik."))
        else:
            items.append(ScoreItem("p1", "Netmeter / P1", 0, 20, "missing",
                "⚠️ Geen netmeter geconfigureerd. NILM werkt niet zonder stroommeting."))

        # ── 2. Fase-sensoren (15 pt) ──────────────────────────────────────────
        phase_count = int(cfg.get("phase_count") or 1)
        has_phase_sensors = any([
            cfg.get("power_sensor_l1"), cfg.get("power_sensor_l2"), cfg.get("power_sensor_l3"),
            cfg.get("phase_sensors_L1"), cfg.get("phase_sensors_L2"), cfg.get("phase_sensors_L3"),
        ])
        has_phase_balance = bool(cfg.get("phase_balance_enabled"))

        if phase_count >= 3 and has_phase_sensors and has_phase_balance:
            items.append(ScoreItem("phases", "3-fase sensoren + balans", 15, 15, "ok"))
        elif phase_count >= 3 and has_phase_sensors:
            items.append(ScoreItem("phases", "3-fase sensoren", 10, 15, "partial",
                "Tip: Activeer fase-balans voor optimale verdeling over L1/L2/L3."))
        elif phase_count >= 3:
            items.append(ScoreItem("phases", "3-fase (geen per-fase sensoren)", 5, 15, "partial",
                "Tip: Voeg per-fase vermogenssensoren toe voor betere NILM-nauwkeurigheid."))
        else:
            items.append(ScoreItem("phases", "1-fase installatie", 10, 15, "ok",
                "1-fase installatie: maximaal 10 van 15 punten beschikbaar."))

        # ── 3. PV-omvormer (15 pt) ────────────────────────────────────────────
        has_solar     = bool(cfg.get("solar_sensor"))
        has_inverters = bool(cfg.get("inverter_configs") and len(cfg.get("inverter_configs", [])) > 0)

        if has_inverters:
            inv_count = len(cfg.get("inverter_configs", []))
            items.append(ScoreItem("pv", f"PV-omvormer(s) ({inv_count}×)", 15, 15, "ok"))
        elif has_solar:
            items.append(ScoreItem("pv", "Totaal PV-sensor", 10, 15, "partial",
                "Tip: Configureer per-omvormer sensoren voor clipping-detectie en fase-toewijzing."))
        else:
            items.append(ScoreItem("pv", "PV-omvormer", 0, 15, "missing",
                "Geen PV geconfigureerd. Sla over als u geen zonnepanelen heeft."))

        # ── 4. Energieprijzen EPEX (10 pt) ────────────────────────────────────
        country = cfg.get("energy_prices_country") or cfg.get("epex_country") or ""
        has_prices = bool(country and country.upper() != "NONE")

        if has_prices:
            items.append(ScoreItem("prices", f"Energieprijzen ({country.upper()})", 10, 10, "ok"))
        else:
            items.append(ScoreItem("prices", "Energieprijzen (EPEX)", 0, 10, "missing",
                "Stel uw land in voor dynamische EPEX-tarieven en goedkope-uur planning."))

        # ── 5. AI-provider (10 pt) ────────────────────────────────────────────
        ai_provider = cfg.get("ai_provider") or _AI_PROVIDER_NONE
        has_cloud   = bool(cfg.get("cloud_api_key") and ai_provider not in (_AI_PROVIDER_NONE, ""))
        has_ollama  = bool(cfg.get("ollama_enabled") or ai_provider == "ollama")
        has_local   = ai_provider == "local_ai"

        if has_cloud:
            items.append(ScoreItem("ai", "Cloud AI actief", 10, 10, "ok"))
        elif has_ollama:
            items.append(ScoreItem("ai", "Lokale AI (Ollama)", 8, 10, "ok"))
        elif has_local:
            items.append(ScoreItem("ai", "Lokale AI actief", 7, 10, "ok"))
        else:
            items.append(ScoreItem("ai", "AI-provider", 3, 10, "partial",
                "Tip: Configureer een AI-provider (Ollama of Cloud) voor betere apparaatidentificatie."))

        # ── 6. EV-lader (8 pt) ───────────────────────────────────────────────
        has_ev = bool(cfg.get("ev_charger_entity"))
        has_ev_smart = bool(cfg.get("ev_smart_schedule") or cfg.get("dynamic_ev_charging_enabled"))

        if has_ev and has_ev_smart:
            items.append(ScoreItem("ev", "EV-lader + slim laden", 8, 8, "ok"))
        elif has_ev:
            items.append(ScoreItem("ev", "EV-lader geconfigureerd", 5, 8, "partial",
                "Tip: Activeer slim laden voor automatische laadsturing op goedkope uren."))
        else:
            items.append(ScoreItem("ev", "EV-lader", 0, 8, "missing",
                "Geen EV-lader. Sla over als u geen elektrisch voertuig heeft."))

        # ── 7. Thuisbatterij (8 pt) ───────────────────────────────────────────
        has_battery = bool(cfg.get("battery_sensor") or
                           (cfg.get("battery_configs") and len(cfg.get("battery_configs", [])) > 0))
        has_batt_scheduler = bool(cfg.get("battery_scheduler_enabled"))

        if has_battery and has_batt_scheduler:
            items.append(ScoreItem("battery", "Batterij + planning", 8, 8, "ok"))
        elif has_battery:
            items.append(ScoreItem("battery", "Batterij geconfigureerd", 5, 8, "partial",
                "Tip: Activeer de batterijplanner voor optimale laad/ontlaad-strategie."))
        else:
            items.append(ScoreItem("battery", "Thuisbatterij", 0, 8, "missing",
                "Geen batterij. Sla over als u geen thuisbatterij heeft."))

        # ── 8. Gas-sensor (5 pt) ─────────────────────────────────────────────
        has_gas = bool(cfg.get("gas_sensor") or (cfg.get("p1_enabled") and has_p1))

        if has_gas:
            items.append(ScoreItem("gas", "Gas-sensor", 5, 5, "ok"))
        else:
            items.append(ScoreItem("gas", "Gas-sensor", 0, 5, "missing",
                "Voeg een gas-sensor toe (of P1-lezer) voor gasverbruik en -anomalie detectie."))

        # ── 9. Tariefinstellingen (5 pt) ──────────────────────────────────────
        has_tax     = bool(cfg.get("price_include_tax") or cfg.get("price_include_btw"))
        has_markup  = bool(cfg.get("selected_supplier") or float(cfg.get("supplier_markup") or 0) > 0)
        has_energy_tax = bool(cfg.get("energy_tax") and float(cfg.get("energy_tax") or 0) > 0)

        tarief_score = (2 if has_tax else 0) + (2 if has_markup else 0) + (1 if has_energy_tax else 0)
        if tarief_score >= 4:
            items.append(ScoreItem("tariff", "Tariefinstellingen compleet", tarief_score, 5, "ok"))
        elif tarief_score > 0:
            items.append(ScoreItem("tariff", "Tariefinstellingen gedeeltelijk", tarief_score, 5, "partial",
                "Stel energiebelasting, BTW en leveranciersopslag in voor nauwkeurige kostenberekening."))
        else:
            items.append(ScoreItem("tariff", "Tariefinstellingen", 0, 5, "missing",
                "Vul energiebelasting en leveranciersinstellingen in voor correcte kosten."))

        # ── 10. Overig (6 pt) — uitgebreid v4.0.4 ──────────────────────────────
        extras = 0
        extra_tips = []
        if cfg.get("heat_pump_power_entity"):
            extras += 2
        else:
            extra_tips.append("warmtepomp-sensor")
        if cfg.get("notification_service"):
            extras += 1
        else:
            extra_tips.append("notificatie-service")
        if cfg.get("peak_shaving_enabled"):
            extras += 1
        else:
            extra_tips.append("piekbeperking")
        if cfg.get("battery_scheduler_enabled") and has_battery:
            extras += 1
        if cfg.get("export_limit_alert_enabled") or cfg.get("saldering_tracking"):
            extras += 1

        status = "ok" if extras >= 5 else ("partial" if extras > 0 else "missing")
        tip = f"Tip: Configureer {', '.join(extra_tips)} voor meer functionaliteit." if extra_tips else ""
        items.append(ScoreItem("extras", f"Geavanceerde features ({extras}/6)", extras, 6, status, tip))

        # ── Totaalscore ───────────────────────────────────────────────────────
        total   = sum(i.points for i in items)
        max_tot = sum(i.max_pts for i in items)
        # Normaliseer naar 100 (sommige items zijn optioneel/n.v.t.)
        score   = round(total / max_tot * 100) if max_tot else 0
        grade   = "A" if score >= 90 else "B" if score >= 70 else "C" if score >= 50 else "D"

        # Samenvatting
        missing = [i.label for i in items if i.status == "missing" and i.points == 0
                   and i.max_pts >= 10]
        if missing:
            summary = f"Score {score}/100 — ontbrekend: {', '.join(missing[:2])}."
        else:
            summary = f"Score {score}/100 — installatie goed geconfigureerd."

        result = InstallationScore(score=score, grade=grade, items=items, summary=summary)
        _LOGGER.debug("CloudEMS installatie-score: %d/100 (%s)", score, grade)

        # Trend bijhouden
        import datetime as _dt
        today = _dt.date.today().isoformat()
        if not self._trend or self._trend[-1]["date"] != today:
            self._trend.append({"date": today, "score": score})
            # Behoud alleen de laatste _TREND_DAYS dagen
            if len(self._trend) > self._TREND_DAYS:
                self._trend = self._trend[-self._TREND_DAYS:]
            self._dirty = True

        return result
