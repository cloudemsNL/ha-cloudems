# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
tariff_consistency.py — v4.6.531

Vergelijkt de EPEX-prijzen die CloudEMS gebruikt met wat HA-sensoren rapporteren.

Problemen die dit detecteert:
  - Verkeerde leveranciersmarge ingesteld (te hoog/laag)
  - BTW-factor fout (21% vs 9% vs 0%)
  - Verkeerde tijdzone in prijs-sensor (prijs van verkeerd uur)
  - CloudEMS gebruikt andere bron dan HA-integratie

Werking:
  - Vergelijk cloudems_price_eur_kwh met HA-sensoren die EPEX melden
    (Tibber, ENTSO-E integratie, Nordpool, Zonneplan)
  - EMA van relatieve afwijking per uur
  - Waarschuw als structureel >15% afwijkt

Zelflerend: leert per-uur systematische afwijkingen.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_tariff_consistency_v1"
STORAGE_VERSION = 1

EMA_ALPHA   = 0.10
MIN_SAMPLES = 12   # ~2 uur bij elke 10s cyclus... nee: per uur-bucket
SAVE_INTERVAL = 30

# Afwijkingsdrempels (relatief)
OK_FRAC   = 0.10    # <10% ok — leveranciersmarge varieert licht
WARN_FRAC = 0.20    # >20% = mogelijk verkeerde instelling
ALERT_FRAC = 0.35   # >35% = waarschijnlijk fout

# Keywords om EPEX/tarief-sensoren te herkennen in HA
PRICE_KEYWORDS = [
    "tibber", "nordpool", "entso", "entsoe", "epex",
    "current_price", "electricity_price", "spotprice",
    "zonneplan", "price_now", "prijs_nu",
]


@dataclass
class TariffHourStats:
    ema_ratio:    float = 1.0   # cloudems / extern
    sample_count: int   = 0

    def to_dict(self) -> dict:
        return {"r": round(self.ema_ratio, 4), "n": self.sample_count}

    def from_dict(self, d: dict) -> None:
        self.ema_ratio    = float(d.get("r", 1.0))
        self.sample_count = int(d.get("n", 0))


class TariffConsistencyMonitor:
    """
    Vergelijkt CloudEMS EPEX-prijs met externe HA-sensoren.
    """

    def __init__(self, hass) -> None:
        self._hass   = hass
        self._store  = None
        # {hour: TariffHourStats}
        self._hourly: Dict[int, TariffHourStats] = {
            h: TariffHourStats() for h in range(24)
        }
        self._ema_global_ratio: float = 1.0
        self._global_samples:   int   = 0
        self._dirty_count       = 0
        self._hint_engine       = None
        self._decisions_history = None
        self._known_price_eids: list[str] = []
        self._discovery_ts: float = 0.0

    def set_hint_engine(self, he) -> None:
        self._hint_engine = he

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY)
        data = await self._store.async_load()
        if data:
            for h_str, d in data.get("hourly", {}).items():
                try:
                    h = int(h_str)
                    if 0 <= h < 24:
                        self._hourly[h].from_dict(d)
                except (ValueError, TypeError):
                    pass
            self._ema_global_ratio = float(data.get("global_ratio", 1.0))
            self._global_samples   = int(data.get("global_samples", 0))

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save({
                "hourly": {str(h): v.to_dict() for h, v in self._hourly.items()},
                "global_ratio":   round(self._ema_global_ratio, 4),
                "global_samples": self._global_samples,
            })
            self._dirty_count = 0

    def observe(
        self,
        cloudems_price_eur_kwh: Optional[float],
        hour: int,
    ) -> Optional[dict]:
        """
        Vergelijk CloudEMS prijs met gevonden HA-sensoren.
        Geeft dict terug met resultaat, of None als geen externe sensor gevonden.
        """
        if cloudems_price_eur_kwh is None or cloudems_price_eur_kwh <= 0:
            return None

        # Herdicover externe sensoren elke 10 minuten
        now = time.time()
        if now - self._discovery_ts > 600:
            self._discovery_ts = now
            self._known_price_eids = self._discover_price_sensors()

        if not self._known_price_eids:
            return None

        # Lees externe sensoren
        external_prices = []
        for eid in self._known_price_eids:
            state = self._hass.states.get(eid)
            if not state or state.state in ("unavailable", "unknown"):
                continue
            try:
                val = float(state.state)
                if 0.001 <= val <= 5.0:   # plausibel bereik €/kWh
                    external_prices.append(val)
            except (ValueError, TypeError):
                pass

        if not external_prices:
            return None

        ext_avg = sum(external_prices) / len(external_prices)
        ratio   = cloudems_price_eur_kwh / ext_avg
        ratio   = max(0.1, min(10.0, ratio))

        # Update statistieken
        h_stats = self._hourly[hour % 24]
        h_stats.ema_ratio    = EMA_ALPHA * ratio + (1 - EMA_ALPHA) * h_stats.ema_ratio
        h_stats.sample_count = min(h_stats.sample_count + 1, 9999)

        self._ema_global_ratio = EMA_ALPHA * ratio + (1 - EMA_ALPHA) * self._ema_global_ratio
        self._global_samples   = min(self._global_samples + 1, 9999)
        self._dirty_count     += 1

        # Classificeer en waarschuw
        rel_dev = abs(self._ema_global_ratio - 1.0)
        if self._global_samples >= MIN_SAMPLES:
            if rel_dev > ALERT_FRAC:
                self._emit_hint(cloudems_price_eur_kwh, ext_avg, rel_dev)
            elif rel_dev > WARN_FRAC and self._global_samples >= MIN_SAMPLES * 3:
                self._emit_hint(cloudems_price_eur_kwh, ext_avg, rel_dev, level="warning")

        return {
            "cloudems_eur_kwh": round(cloudems_price_eur_kwh, 4),
            "external_eur_kwh": round(ext_avg, 4),
            "ratio":            round(ratio, 3),
            "ema_ratio":        round(self._ema_global_ratio, 3),
            "deviation_pct":    round(rel_dev * 100, 1),
            "samples":          self._global_samples,
            "external_sensors": self._known_price_eids,
        }

    def _discover_price_sensors(self) -> list[str]:
        """Autodiscover HA-sensoren die EPEX/tariefprijzen melden."""
        found = []
        for state in self._hass.states.async_all("sensor"):
            eid   = state.entity_id
            name  = (state.attributes.get("friendly_name") or "").lower()
            combo = eid.lower() + " " + name
            if not any(kw in combo for kw in PRICE_KEYWORDS):
                continue
            if state.attributes.get("unit_of_measurement") not in ("€/kWh", "EUR/kWh", "ct/kWh"):
                continue
            if state.state in ("unavailable", "unknown"):
                continue
            # Sluit CloudEMS eigen sensoren uit
            if "cloudems" in eid.lower():
                continue
            try:
                val = float(state.state)
                if 0.001 <= val <= 5.0:
                    found.append(eid)
            except (ValueError, TypeError):
                pass
        if found:
            _LOGGER.debug("TariffConsistency: gevonden externe prijs-sensoren: %s", found)
        return found

    def _emit_hint(
        self,
        cloudems_price: float,
        external_price: float,
        rel_dev: float,
        level: str = "alert",
    ) -> None:
        if not self._hint_engine:
            return
        direction = "hoger" if cloudems_price > external_price else "lager"
        try:
            self._hint_engine._emit_hint(
                hint_id    = "tariff_consistency",
                title      = "EPEX-prijs wijkt af van externe sensor",
                message    = (
                    f"CloudEMS gebruikt {cloudems_price*100:.1f} ct/kWh maar externe "
                    f"sensoren meten gemiddeld {external_price*100:.1f} ct/kWh "
                    f"({rel_dev*100:.0f}% {direction}). "
                    f"Mogelijke oorzaken: verkeerde leveranciersmarge, BTW-instelling, "
                    f"of tijdzoneverschil. Controleer via Instellingen → CloudEMS → Prijzen."
                ),
                action     = "Controleer leveranciersmarge en BTW in CloudEMS",
                confidence = min(0.90, 0.5 + rel_dev),
            )
        except Exception as _e:
            _LOGGER.debug("TariffConsistency hint fout: %s", _e)

    def get_diagnostics(self) -> dict:
        return {
            "global_ratio":   round(self._ema_global_ratio, 3),
            "global_samples": self._global_samples,
            "deviation_pct":  round(abs(self._ema_global_ratio - 1.0) * 100, 1),
            "known_sensors":  self._known_price_eids,
            "hourly": {
                h: {"ratio": round(v.ema_ratio, 3), "samples": v.sample_count}
                for h, v in self._hourly.items()
                if v.sample_count > 0
            },
        }
