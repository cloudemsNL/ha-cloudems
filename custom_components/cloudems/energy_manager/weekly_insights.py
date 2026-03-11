# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Wekelijkse Vergelijking + Blueprint Generator (v2.6).

WEKELIJKSE VERGELIJKING
  Berekent verschil t.o.v. vorige week in:
  • Totaal verbruik (kWh)
  • Kosten (€)
  • Zonne-energie (kWh)
  • Top-apparaat (meeste verbruik)

  Stuur samenvatting elke maandag om 08:00 via persistent notification.

HA BLUEPRINT GENERATOR
  Genereert kant-en-klare HA automation YAML bestanden op basis van:
  • Beschikbare NILM-apparaten
  • Actuele tariefdrempels
  • Geconfigureerde entiteiten

  Schrijft naar /config/blueprints/cloudems/ als .yaml bestanden.
"""
from __future__ import annotations
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# ── Wekelijkse vergelijking ───────────────────────────────────────────────────

class WeeklyComparison:
    """Vergelijkt huidig weekverbruik met vorige week."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self._hass        = hass
        self._this_week:  dict = {}   # accumulatie huidige week
        self._last_week:  dict = {}   # kopie van vorige week
        self._week_number = datetime.now(timezone.utc).isocalendar()[1]
        self._last_sent_week = -1

    def update(self, data: dict) -> None:
        """Update weekaccumulatie vanuit coordinator data. Aanroepen elke cyclus."""
        now   = datetime.now(timezone.utc)
        w_now = now.isocalendar()[1]

        # Weekwissel detecteren
        if w_now != self._week_number:
            self._last_week  = dict(self._this_week)
            self._this_week  = {}
            self._week_number = w_now

        # Accumuleer (we nemen de actuele dagwaarden als proxy)
        kwh_today   = float(data.get("import_kwh_today", 0) or 0)
        cost_today  = float(data.get("cost_today_eur", 0) or 0)
        solar_today = float(data.get("solar_kwh_today", 0) or 0)
        day_key     = now.strftime("%Y-%m-%d")

        self._this_week.setdefault("days", {})
        self._this_week["days"][day_key] = {
            "kwh":   kwh_today,
            "cost":  cost_today,
            "solar": solar_today,
        }

    def get_comparison(self) -> dict:
        """Geef vergelijking huidig vs vorige week."""
        this  = self._aggregate(self._this_week.get("days", {}))
        last  = self._aggregate(self._last_week.get("days", {}))

        def delta(a, b, fmt=".1f"):
            if b == 0:
                return None
            d = ((a - b) / b) * 100
            return round(d, 1)

        return {
            "this_week_kwh":    this["kwh"],
            "last_week_kwh":    last["kwh"],
            "kwh_delta_pct":    delta(this["kwh"], last["kwh"]),
            "this_week_cost":   this["cost"],
            "last_week_cost":   last["cost"],
            "cost_delta_pct":   delta(this["cost"], last["cost"]),
            "this_week_solar":  this["solar"],
            "last_week_solar":  last["solar"],
            "solar_delta_pct":  delta(this["solar"], last["solar"]),
            "week_number":      self._week_number,
        }

    def _aggregate(self, days: dict) -> dict:
        return {
            "kwh":   round(sum(d["kwh"]   for d in days.values()), 2),
            "cost":  round(sum(d["cost"]  for d in days.values()), 2),
            "solar": round(sum(d["solar"] for d in days.values()), 2),
        }

    async def maybe_send_weekly(self, data: dict) -> bool:
        """Stuur samenvatting elke maandag om 08:00."""
        now = datetime.now(timezone.utc)
        if now.weekday() != 0 or now.hour != 8:  # 0 = maandag
            return False
        if self._last_sent_week == self._week_number:
            return False

        self.update(data)
        cmp = self.get_comparison()
        msg = self._build_message(cmp, data)

        try:
            from homeassistant.components.persistent_notification import async_create
            async_create(
                self._hass, message=msg,
                title=f"📊 CloudEMS Weekoverzicht — week {cmp['week_number']}",
                notification_id=f"cloudems_weekly_{cmp['week_number']}",
            )
            self._last_sent_week = self._week_number
            return True
        except Exception as err:
            _LOGGER.warning("CloudEMS weekoverzicht mislukt: %s", err)
            return False

    def _build_message(self, cmp: dict, data: dict) -> str:
        def arrow(pct):
            if pct is None:
                return "—"
            return f"▲ {abs(pct):.0f}%" if pct > 0 else f"▼ {abs(pct):.0f}%"

        lines = [f"## 📊 Weekvergelijking — week {cmp['week_number']}\n"]
        lines.append(f"**Verbruik:** {cmp['this_week_kwh']:.1f} kWh {arrow(cmp['kwh_delta_pct'])} t.o.v. vorige week")
        lines.append(f"**Kosten:** €{cmp['this_week_cost']:.2f} {arrow(cmp['cost_delta_pct'])}")
        lines.append(f"**Zonne-energie:** {cmp['this_week_solar']:.1f} kWh {arrow(cmp['solar_delta_pct'])}")

        # Top-apparaat
        nilm = data.get("nilm_devices") or []
        if nilm:
            top = max(nilm, key=lambda d: float(d.get("power_w", 0) or 0), default=None)
            if top:
                lines.append(f"\n**Meest actief:** {top.get('name', top.get('device_type', '?'))}")

        lines.append("\n*Automatisch gegenereerd door CloudEMS*")
        return "\n".join(lines)


# ── Blueprint Generator ───────────────────────────────────────────────────────

BLUEPRINT_TEMPLATES = {
    "washer_shift": """blueprint:
  name: "CloudEMS — Verschuif {device_name} naar goedkoop uur"
  description: >
    Stuur een notificatie als {device_name} aanslaat tijdens een hoge stroomprijs.
    Gegenereerd door CloudEMS v2.6.
  domain: automation
  input:
    price_sensor:
      name: Stroomprijs sensor
      default: sensor.cloudems_energy_price
      selector:
        entity:
          domain: sensor
    high_price_threshold:
      name: Hoge prijs drempel (€/kWh)
      default: {high_threshold}
      selector:
        number:
          min: 0.05
          max: 1.00
          step: 0.01
    notify_service:
      name: Notificatie service
      default: notify.notify
      selector:
        text:

trigger:
  - platform: state
    entity_id: sensor.cloudems_nilm_{device_id}
    to: "on"

condition:
  - condition: numeric_state
    entity_id: !input price_sensor
    above: !input high_price_threshold

action:
  - service: !input notify_service
    data:
      title: "💡 Verschuif {device_name}?"
      message: >
        {device_name} is gestart bij hoge stroomprijs
        ({{{{ states('sensor.cloudems_energy_price') }}}} €/kWh).
        Overweeg te wachten op een goedkoper moment.
""",

    "negative_tariff": """blueprint:
  name: "CloudEMS — Negatief tarief actie"
  description: >
    Schakel extra verbruikers in bij een negatieve stroomprijs.
    Gegenereerd door CloudEMS v2.6.
  domain: automation
  input:
    price_sensor:
      name: Stroomprijs sensor
      default: sensor.cloudems_energy_price
      selector:
        entity:
          domain: sensor
    switch_to_enable:
      name: Schakelaar om in te schakelen
      selector:
        entity:
          domain: switch

trigger:
  - platform: numeric_state
    entity_id: !input price_sensor
    below: 0.0

action:
  - service: switch.turn_on
    target:
      entity_id: !input switch_to_enable
  - service: notify.notify
    data:
      title: "⚡ Negatief stroomtarief!"
      message: >
        Stroomprijs is {{{{ states('sensor.cloudems_energy_price') }}}} €/kWh.
        Extra verbruikers ingeschakeld.
""",

    "sleep_mode": """blueprint:
  name: "CloudEMS — Slaapstand automatisering"
  description: >
    Schakel apparaten uit als CloudEMS slaapstand detecteert.
    Gegenereerd door CloudEMS v2.6.
  domain: automation
  input:
    switches_to_off:
      name: Uitschakelen bij slaapstand
      selector:
        entity:
          domain: switch
          multiple: true

trigger:
  - platform: state
    entity_id: sensor.cloudems_slaapstand
    to: "actief"

action:
  - service: switch.turn_off
    target:
      entity_id: !input switches_to_off
""",

    "peak_warning": """blueprint:
  name: "CloudEMS — Kwartier-piekwaarschuwing"
  description: >
    Stuur notificatie als de 15-minuten vermogenspiek dreigt overschreden te worden.
    Gegenereerd door CloudEMS v2.6.
  domain: automation
  input:
    notify_service:
      name: Notificatie service
      default: notify.notify
      selector:
        text:

trigger:
  - platform: state
    entity_id: binary_sensor.cloudems_kwartier_piek_waarschuwing
    to: "on"

action:
  - service: !input notify_service
    data:
      title: "⚠️ CloudEMS — Piekwaarschuwing"
      message: >
        Kwartier-piek dreigt maandrecord te overtreffen!
        Huidig gemiddelde: {{{{ state_attr('sensor.cloudems_kwartier_piek', 'current_avg_w') | int }}}} W.
        Schakel grote verbruikers tijdelijk uit.
""",
}


class BlueprintGenerator:
    """Genereert HA automation blueprints op basis van CloudEMS configuratie."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass   = hass
        self._config = config

    async def async_generate_all(self, nilm_devices: list[dict]) -> list[str]:
        """Genereer alle relevante blueprints. Geeft lijst van gegenereerde bestandsnamen."""
        blueprints_dir = pathlib.Path(self._hass.config.config_dir) / "blueprints" / "automation" / "cloudems"
        await self._hass.async_add_executor_job(blueprints_dir.mkdir, 0o755, True, True)

        generated = []
        threshold = float(self._config.get("shift_high_tariff_threshold", 0.28))

        # Blueprint per wasapparaat
        for dev in nilm_devices:
            dtype = dev.get("device_type", "")
            if dtype in {"washer", "washing_machine", "dryer", "dishwasher"}:
                name    = dev.get("name") or dtype.replace("_", " ").title()
                dev_id  = dev.get("device_id", dtype)
                content = BLUEPRINT_TEMPLATES["washer_shift"].format(
                    device_name=name,
                    device_id=dev_id,
                    high_threshold=threshold,
                )
                fname = f"verschuif_{dev_id}.yaml"
                await self._write(blueprints_dir / fname, content)
                generated.append(fname)

        # Negatief tarief
        await self._write(blueprints_dir / "negatief_tarief.yaml", BLUEPRINT_TEMPLATES["negative_tariff"])
        generated.append("negatief_tarief.yaml")

        # Slaapstand
        await self._write(blueprints_dir / "slaapstand.yaml", BLUEPRINT_TEMPLATES["sleep_mode"])
        generated.append("slaapstand.yaml")

        # Piekwaarschuwing
        await self._write(blueprints_dir / "piekwaarschuwing.yaml", BLUEPRINT_TEMPLATES["peak_warning"])
        generated.append("piekwaarschuwing.yaml")

        _LOGGER.info("CloudEMS blueprints gegenereerd: %s", generated)
        return generated

    async def _write(self, path: pathlib.Path, content: str) -> None:
        await self._hass.async_add_executor_job(path.write_text, content, "utf-8")
