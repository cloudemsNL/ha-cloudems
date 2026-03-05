"""
CloudEMS Goedkope Uren Schakelaar Planner — v1.20.0

Schakelt HA switch/input_boolean entiteiten automatisch AAN tijdens het
goedkoopste N-uursblok van de dag, en laat ze daarna op hun huidige stand.

Ontwerpkeuze: ALLEEN aanzetten, nooit uitzetten.
  - Gebruiker zet apparaat handmatig uit als hij klaar is.
  - CloudEMS zet het AAN zodra het goedkoopste blok begint.
  - Dit is veilig voor apparaten die niet mogen worden afgebroken
    (bijv. wasmachine halverwege het programma).

Typisch gebruik:
  - Wasmachine of droger: "zet AAN in goedkoopste 4 uur, ik heb het
    al gevuld en klaargezet."
  - Vaatwasser: "zet AAN in goedkoopste 3 uur 's nachts."
  - Extra boiler opwarm-uur: "zet AAN in goedkoopste uur."

Configuratie (per schakelaar):
  entity_id:        switch.wasmachine / input_boolean.start_droger
  window_hours:     2 | 3 | 4          → welk goedkoopste blok
  earliest_hour:    6                  → niet vóór dit uur starten (bijv. geen nacht)
  latest_hour:      22                 → niet ná dit uur starten
  days:             [0,1,2,3,4,5,6]   → weekdagen (0=ma, 6=zo), leeg = altijd
  active:           true               → aan/uit

Werking per 10-seconden-tick:
  1. Haal cheapest_Nh_start op uit price_info
  2. Controleer of huidig uur == start_hour EN in tijdvenster EN op geldige dag
  3. Lees huidige schakelaar-staat — als al AAN: skip
  4. Zet schakelaar AAN via hass.services.async_call
  5. Log + cooldown van 1 uur (zodat switch niet elke 10s opnieuw aan gaat)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Na het aanzetten: minimale wachttijd voor dezelfde schakelaar (seconden)
# Voorkomt dat dezelfde schakelaar elke 10s opnieuw wordt aangezet.
COOLDOWN_S = 3600   # 1 uur


@dataclass
class CheapSwitchConfig:
    """Configuratie voor één schakelaar die aan goedkope uren gekoppeld is."""
    entity_id:    str
    window_hours: int   = 4       # 1 | 2 | 3 | 4
    earliest_hour: int  = 0       # niet vóór dit uur starten (lokale tijd)
    latest_hour:  int   = 23      # niet ná dit uur starten
    days:         list  = field(default_factory=list)   # [] = elke dag
    active:       bool  = True

    @classmethod
    def from_dict(cls, d: dict) -> "CheapSwitchConfig":
        return cls(
            entity_id    = d.get("entity_id", ""),
            window_hours = int(d.get("window_hours", 4)),
            earliest_hour= int(d.get("earliest_hour", 0)),
            latest_hour  = int(d.get("latest_hour", 23)),
            days         = list(d.get("days", [])),
            active       = bool(d.get("active", True)),
        )

    def to_dict(self) -> dict:
        return {
            "entity_id":    self.entity_id,
            "window_hours": self.window_hours,
            "earliest_hour":self.earliest_hour,
            "latest_hour":  self.latest_hour,
            "days":         self.days,
            "active":       self.active,
        }


class CheapSwitchScheduler:
    """
    Beheert alle goedkope-uren schakelaar koppelingen.

    Gebruik vanuit coordinator (elke 10s tick):
        result = await scheduler.async_evaluate(price_info)
    """

    def __init__(self, hass: HomeAssistant, configs: list[dict]) -> None:
        self._hass    = hass
        self._configs = [CheapSwitchConfig.from_dict(c) for c in configs if c.get("entity_id")]
        self._last_triggered: dict[str, float] = {}   # entity_id → timestamp

    def update_configs(self, configs: list[dict]) -> None:
        """Update configuratie (bijv. na wizard-wijziging)."""
        self._configs = [CheapSwitchConfig.from_dict(c) for c in configs if c.get("entity_id")]

    async def async_evaluate(self, price_info: dict) -> list[dict]:
        """
        Evalueer alle schakelaars en zet aan indien nodig.

        Args:
            price_info: dict van EnergyPriceFetcher.get_price_info()

        Returns:
            Lijst van actie-dicts voor logging/sensor output.
        """
        if not self._configs:
            return []

        now_utc  = datetime.now(timezone.utc)
        now_local = datetime.now()   # lokale tijd voor hour/weekday check
        now_h    = now_local.hour
        now_wday = now_local.weekday()   # 0=ma, 6=zo
        now_ts   = time.time()

        actions = []

        for cfg in self._configs:
            if not cfg.active or not cfg.entity_id:
                continue

            # Bepaal het goedkoopste startuur voor dit venster
            start_key = f"cheapest_{cfg.window_hours}h_start"
            start_hour = price_info.get(start_key)
            if start_hour is None:
                continue

            # Controleer of we in het juiste uur zitten
            if now_h != start_hour:
                continue

            # Tijdvenster controle (earliest/latest)
            if now_h < cfg.earliest_hour or now_h > cfg.latest_hour:
                _LOGGER.debug(
                    "CheapSwitch: %s overgeslagen — uur %d buiten venster %d-%d",
                    cfg.entity_id, now_h, cfg.earliest_hour, cfg.latest_hour
                )
                continue

            # Weekdag controle
            if cfg.days and now_wday not in cfg.days:
                continue

            # Cooldown controle — niet vaker dan eens per uur aansturen
            last_t = self._last_triggered.get(cfg.entity_id, 0)
            if now_ts - last_t < COOLDOWN_S:
                continue

            # Lees huidige staat — als al AAN, skip
            state = self._hass.states.get(cfg.entity_id)
            if state is None:
                _LOGGER.warning("CheapSwitch: entiteit '%s' niet gevonden in HA", cfg.entity_id)
                continue
            if state.state in ("on", "true", "1"):
                _LOGGER.debug("CheapSwitch: %s al AAN — skip", cfg.entity_id)
                # Registreer toch cooldown zodat we niet elke tick loggen
                self._last_triggered[cfg.entity_id] = now_ts
                actions.append({
                    "entity_id": cfg.entity_id,
                    "action":    "already_on",
                    "reason":    f"Goedkoopste {cfg.window_hours}u blok start {start_hour:02d}:00, al actief",
                })
                continue

            # Zet schakelaar AAN
            domain = cfg.entity_id.split(".")[0]
            service = "turn_on"
            try:
                await self._hass.services.async_call(
                    domain, service,
                    {"entity_id": cfg.entity_id},
                    blocking=False,
                )
                self._last_triggered[cfg.entity_id] = now_ts
                _LOGGER.info(
                    "CheapSwitch: %s AAN gezet — goedkoopste %dh blok start %02d:00 (prijs ~€%.4f/kWh)",
                    cfg.entity_id, cfg.window_hours, start_hour,
                    price_info.get("current", 0),
                )
                actions.append({
                    "entity_id":   cfg.entity_id,
                    "action":      "turned_on",
                    "window_hours":cfg.window_hours,
                    "start_hour":  start_hour,
                    "reason":      f"Goedkoopste {cfg.window_hours}u blok begint nu ({start_hour:02d}:00)",
                })
            except Exception as exc:
                _LOGGER.error("CheapSwitch: fout bij aansturen %s: %s", cfg.entity_id, exc)

        return actions

    def get_status(self, price_info: dict) -> list[dict]:
        """Return huidige status van alle gekoppelde schakelaars (voor sensor output)."""
        now_local = datetime.now()
        now_h = now_local.hour
        result = []
        for cfg in self._configs:
            start_key = f"cheapest_{cfg.window_hours}h_start"
            start_hour = price_info.get(start_key)
            block_key  = f"cheapest_{cfg.window_hours}h_block"
            block      = price_info.get(block_key, {}) or {}

            state = self._hass.states.get(cfg.entity_id)
            current_state = state.state if state else "unavailable"

            in_block = bool(block and now_h in block.get("hours", []))
            result.append({
                "entity_id":    cfg.entity_id,
                "window_hours": cfg.window_hours,
                "start_hour":   start_hour,
                "block_label":  block.get("label", ""),
                "avg_price":    block.get("avg_price"),
                "in_block":     in_block,
                "current_state":current_state,
                "active":       cfg.active,
                "earliest_hour":cfg.earliest_hour,
                "latest_hour":  cfg.latest_hour,
                "days":         cfg.days,
                "last_triggered": self._last_triggered.get(cfg.entity_id),
            })
        return result
