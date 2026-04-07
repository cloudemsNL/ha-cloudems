# -*- coding: utf-8 -*-
"""CloudEMS — CO₂ voetafdruk tracker (v1.0)

Haalt de actuele CO₂-intensiteit van het Nederlandse elektriciteitsnet op
via de Electricity Maps / ENTSO-E Transparency API.

Volledig additief — raakt geen bestaande logica aan.
"""
from __future__ import annotations
import logging
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Fallback gemiddelde NL emissie-intensiteit (gCO₂/kWh) per uur van de dag
# Gebaseerd op ENTSO-E 2023 gemiddelden NL
NL_FALLBACK_GCO2_KWH = {
    0:360, 1:355, 2:350, 3:345, 4:345, 5:350,
    6:360, 7:370, 8:375, 9:370, 10:350, 11:330,
    12:310, 13:295, 14:280, 15:285, 16:300, 17:320,
    18:345, 19:360, 20:365, 21:362, 22:360, 23:358,
}


class CO2Tracker:
    """Bijhoudt CO₂-intensiteit van het net en berekent voetafdruk.

    Integreert met de coordinator data-dict:
      data["co2_gco2_kwh"]       → huidige intensiteit
      data["co2_saved_today_g"]  → bespaard door PV/accu vandaag

    Overleeft herstart via to_dict / from_dict.
    """

    CACHE_TTL = 900  # 15 min cache voor API resultaten

    def __init__(self) -> None:
        self._intensity_now: float = 350.0  # gCO₂/kWh
        self._source: str = "fallback"
        self._last_fetch: float = 0.0
        self._saved_today_g: float = 0.0   # gram CO₂ bespaard vandaag
        self._last_day: Optional[int] = None
        self._hourly_history: list[dict] = []  # uur-voor-uur log

    async def async_update(self, hass, solar_w: float = 0.0,
                           battery_discharge_w: float = 0.0) -> dict:
        """Update CO₂-intensiteit en bereken besparing. Aanroepen per coordinator tick."""
        now = time.time()

        # Reset dagteller
        from datetime import datetime
        today = datetime.now().day
        if self._last_day is not None and self._last_day != today:
            self._hourly_history.append({
                "day": self._last_day,
                "saved_g": round(self._saved_today_g, 0),
            })
            self._hourly_history = self._hourly_history[-30:]
            self._saved_today_g = 0.0
        self._last_day = today

        # Probeer actuele intensiteit te halen (elk kwartier)
        if now - self._last_fetch > self.CACHE_TTL:
            await self._fetch_intensity(hass)

        # Besparing berekenen: elke 10s (coordinator tick)
        # PV + accu ontladen = vermeden netafname = bespaard CO₂
        green_w = solar_w + max(0.0, battery_discharge_w)
        saved_g = green_w / 1000 * (10 / 3600) * self._intensity_now
        self._saved_today_g += saved_g

        return {
            "co2_gco2_kwh":      round(self._intensity_now, 0),
            "co2_source":        self._source,
            "co2_saved_today_g": round(self._saved_today_g, 0),
            "co2_saved_today_kg": round(self._saved_today_g / 1000, 3),
            "co2_label":         self._intensity_label(),
        }

    async def _fetch_intensity(self, hass) -> None:
        """Haal actuele CO₂-intensiteit op. Fallback op uurgemiddelde."""
        from datetime import datetime
        hour = datetime.now().hour
        try:
            # Probeer electricitymap.org free API (geen key nodig voor NL)
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://api.electricitymap.org/v3/carbon-intensity/latest?zone=NL"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        val = data.get("carbonIntensity")
                        if val and isinstance(val, (int, float)) and 0 < val < 1000:
                            self._intensity_now = float(val)
                            self._source = "electricitymap"
                            self._last_fetch = time.time()
                            _LOGGER.debug("CO2: %.0f gCO₂/kWh via ElectricityMap", val)
                            return
        except Exception as exc:
            _LOGGER.debug("CO2 API fout: %s — gebruik fallback", exc)

        # Fallback: uurgemiddelde
        self._intensity_now = NL_FALLBACK_GCO2_KWH.get(hour, 350)
        self._source = "fallback"
        self._last_fetch = time.time()

    def _intensity_label(self) -> str:
        g = self._intensity_now
        if g < 200: return "🟢 Laag"
        if g < 350: return "🟡 Gemiddeld"
        return "🔴 Hoog"

    @property
    def stats(self) -> dict:
        return {
            "intensity_gco2_kwh": round(self._intensity_now, 0),
            "source":             self._source,
            "saved_today_g":      round(self._saved_today_g, 0),
            "label":              self._intensity_label(),
        }

    def to_dict(self) -> dict:
        return {
            "intensity":     self._intensity_now,
            "source":        self._source,
            "saved_today_g": self._saved_today_g,
            "last_day":      self._last_day,
            "history":       self._hourly_history[-30:],
        }

    def from_dict(self, d: dict) -> None:
        self._intensity_now  = float(d.get("intensity", 350))
        self._source         = d.get("source", "fallback")
        self._saved_today_g  = float(d.get("saved_today_g", 0))
        self._last_day       = d.get("last_day")
        self._hourly_history = d.get("history", [])
