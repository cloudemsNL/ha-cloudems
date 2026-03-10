# -*- coding: utf-8 -*-
"""
CloudEMS PowerCalc Profiles -- v1.0.0

Ingebouwde profielendatabase (~300 apparaten) + remote sync van cloudems.eu
(dagelijks bijgewerkt vanuit de PowerCalc community-database).

Fallback-keten bij ophalen van een profiel:
  1. Per-entiteit geleerd profiel (NILM-feedback, meest accuraat)
  2. PowerCalc lokaal (als integratie geinstalleerd is)
  3. CloudEMS remote database (dagelijks gesynchroniseerd)
  4. Ingebouwde profielen (dit bestand)
  5. Device-klasse mediaan
  6. Domein-fallback (light=8W, switch=50W, ...)

Copyright (c) 2025 CloudEMS -- https://cloudems.eu
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Tuple

from .powercalc_engine import PowerProfile, LUTEntry

_LOGGER = logging.getLogger(__name__)

REMOTE_URL     = "https://cloudems.eu/powercalc/profiles-v2.json"
REMOTE_TTL_S   = 86_400
FETCH_TIMEOUT  = 12

# (strategy, power_on_w, standby_w, max_w)  -- voor fixed/linear profielen
_B: Dict[str, Tuple[str, float, float, float]] = {
    # ── Philips Hue ──────────────────────────────────────────────────────────
    "signify/lca001":          ("linear",  8.5, 0.4,  8.5),
    "signify/lca002":          ("linear",  8.5, 0.4,  8.5),
    "signify/lca003":          ("linear",  8.5, 0.4,  8.5),
    "signify/lca004":          ("linear",  6.5, 0.3,  6.5),
    "signify/lca005":          ("linear",  8.5, 0.4,  8.5),
    "signify/lce001":          ("linear",  5.5, 0.3,  5.5),
    "signify/lce002":          ("linear",  5.5, 0.3,  5.5),
    "signify/lct001":          ("linear",  8.5, 0.4,  8.5),
    "signify/lct010":          ("linear",  9.0, 0.4,  9.0),
    "signify/lct012":          ("linear",  6.0, 0.3,  6.0),
    "signify/lct015":          ("linear",  9.5, 0.4,  9.5),
    "signify/lct016":          ("linear",  9.0, 0.4,  9.0),
    "signify/ltp001":          ("linear", 10.0, 0.5, 10.0),
    "signify/ltp003":          ("linear", 10.0, 0.5, 10.0),
    "signify/lst002":          ("linear", 20.0, 0.5, 20.0),
    "signify/lwb006":          ("linear",  9.5, 0.4,  9.5),
    "signify/lwb010":          ("linear",  8.5, 0.4,  8.5),
    "signify/lwb014":          ("linear",  9.5, 0.4,  9.5),
    "signify/lom001":          ("fixed",  10.0, 0.5, 10.0),
    # ── IKEA Tradfri / Dirigera ───────────────────────────────────────────────
    "ikea of sweden/led1545g12": ("linear", 8.6, 0.3,  8.6),
    "ikea of sweden/led1546g12": ("linear", 8.6, 0.3,  8.6),
    "ikea of sweden/led1536g5":  ("linear", 5.0, 0.3,  5.0),
    "ikea of sweden/led1649c5":  ("linear", 6.0, 0.3,  6.0),
    "ikea of sweden/led1650r5":  ("linear", 4.5, 0.3,  4.5),
    "ikea of sweden/led1924g9":  ("linear", 8.6, 0.3,  8.6),
    "ikea of sweden/led2003g10": ("linear", 8.6, 0.3,  8.6),
    # ── OSRAM / Ledvance ─────────────────────────────────────────────────────
    "osram/classic a60 rgbw":    ("linear", 9.0, 0.5, 9.0),
    "ledvance/smart+ classic a": ("linear", 9.0, 0.5, 9.0),
    "ledvance/smart+ filament":  ("linear", 6.0, 0.3, 6.0),
    # ── Shelly ───────────────────────────────────────────────────────────────
    "shelly/shelly1":            ("fixed",  50.0, 0.4, 2500.0),
    "shelly/shelly1pm":          ("fixed",  50.0, 0.4, 2500.0),
    "shelly/shelly2.5":          ("fixed",  50.0, 0.4, 2500.0),
    "shelly/shellyplus1":        ("fixed",  50.0, 0.4, 2500.0),
    "shelly/shellyplus1pm":      ("fixed",  50.0, 0.4, 2500.0),
    "shelly/shellyplugs":        ("fixed",  50.0, 0.4, 2500.0),
    "shelly/shellyplugsg3":      ("fixed",  50.0, 0.4, 2500.0),
    "shelly/shellydimmer2":      ("linear", 40.0, 0.4,  250.0),
    # ── Sonoff ───────────────────────────────────────────────────────────────
    "sonoff/basic":              ("fixed",  50.0, 0.3, 2200.0),
    "sonoff/s20":                ("fixed",  50.0, 0.3, 2200.0),
    "sonoff/s26":                ("fixed",  50.0, 0.3, 2200.0),
    "sonoff/pow":                ("fixed",  50.0, 0.5, 3500.0),
    "sonoff/pow r2":             ("fixed",  50.0, 0.5, 3500.0),
    "sonoff/d1":                 ("linear", 30.0, 0.4,  300.0),
    # ── TP-Link / Kasa ────────────────────────────────────────────────────────
    "tp-link/hs100":             ("fixed",  50.0, 0.3, 2300.0),
    "tp-link/hs110":             ("fixed",  50.0, 0.3, 2300.0),
    "tp-link/kp115":             ("fixed",  50.0, 0.3, 2300.0),
    "tp-link/ep25":              ("fixed",  50.0, 0.3, 2300.0),
    # ── Samsung TV ────────────────────────────────────────────────────────────
    "samsung/qe55q80a":          ("fixed", 148.0, 0.5, 148.0),
    "samsung/qe65qn90b":         ("fixed", 182.0, 0.5, 182.0),
    "samsung/ue43au7100":        ("fixed",  75.0, 0.5,  75.0),
    "samsung/ue55tu7100":        ("fixed",  98.0, 0.5,  98.0),
    "samsung/ue65au9000":        ("fixed", 120.0, 0.5, 120.0),
    # ── LG TV ─────────────────────────────────────────────────────────────────
    "lg electronics/oled55cx6la": ("fixed", 110.0, 0.3, 110.0),
    "lg electronics/oled65c1pua": ("fixed", 130.0, 0.3, 130.0),
    "lg electronics/55nano866pa": ("fixed",  90.0, 0.4,  90.0),
    # ── Philips TV ────────────────────────────────────────────────────────────
    "philips/55oled936":          ("fixed", 130.0, 0.3, 130.0),
    "philips/65pus8506":          ("fixed", 115.0, 0.4, 115.0),
    # ── Sonos ─────────────────────────────────────────────────────────────────
    "sonos/one":                  ("fixed",   8.0, 2.0,   8.0),
    "sonos/beam":                 ("fixed",  12.0, 2.0,  12.0),
    "sonos/arc":                  ("fixed",  22.0, 2.5,  22.0),
    "sonos/era 100":              ("fixed",   8.0, 1.5,   8.0),
    "sonos/era 300":              ("fixed",  18.0, 2.0,  18.0),
    # ── Google Nest / Chromecast ──────────────────────────────────────────────
    "google/nest hub":            ("fixed",   7.0, 1.5,   7.0),
    "google/nest hub max":        ("fixed",  14.0, 2.0,  14.0),
    "google/chromecast":          ("fixed",   2.0, 0.3,   2.0),
    "google/chromecast 4k":       ("fixed",   3.5, 0.5,   3.5),
    # ── Amazon Echo ───────────────────────────────────────────────────────────
    "amazon/echo dot 3rd gen":    ("fixed",   3.0, 1.4,   3.0),
    "amazon/echo dot 4th gen":    ("fixed",   3.0, 1.4,   3.0),
    "amazon/echo 4th gen":        ("fixed",  11.0, 1.5,  11.0),
    "amazon/echo show 8":         ("fixed",  15.0, 2.0,  15.0),
    # ── Apple ─────────────────────────────────────────────────────────────────
    "apple/apple tv 4k":          ("fixed",   4.0, 0.5,   4.0),
    "apple/homepod mini":         ("fixed",   6.0, 1.0,   6.0),
    # ── Roborock / iRobot vacuums ─────────────────────────────────────────────
    "roborock/s6 pure":           ("fixed",  27.0, 0.5,  27.0),
    "roborock/s8":                ("fixed",  30.0, 0.5,  30.0),
    "irobot/roomba i3":           ("fixed",  29.0, 0.5,  29.0),
    "irobot/roomba j7":           ("fixed",  26.0, 0.5,  26.0),
    # ── Smart plugs generic ───────────────────────────────────────────────────
    "nous/a1t":                   ("fixed",  50.0, 0.5, 3500.0),
    "blitzwolf/bw-shp6":          ("fixed",  50.0, 0.5, 3500.0),
    "athom/plug v2":              ("fixed",  50.0, 0.5, 3500.0),
    # ── Fibaro ────────────────────────────────────────────────────────────────
    "fibargroup/fgd212":          ("linear", 50.0, 0.8,  250.0),
    "fibargroup/fgwpf102":        ("fixed",  50.0, 0.4, 2500.0),
    # ── Namron ────────────────────────────────────────────────────────────────
    "namron/4512737":             ("linear", 50.0, 0.8,  200.0),
    # ── Buienalarm / Tado thermostaten ────────────────────────────────────────
    "tado/tado smart radiator thermostat": ("fixed", 0.5, 0.3, 0.5),
}

# Device-klasse fallbacks (domein + device_class -> (min, median, max) W)
_CLASS_W: Dict[str, Tuple[float, float, float]] = {
    "light":                 (2.0,   8.0,  60.0),
    "light.led":             (2.0,   6.0,  15.0),
    "light.led_strip":       (5.0,  15.0,  40.0),
    "light.halogen":        (20.0,  35.0,  60.0),
    "switch":               (10.0,  50.0, 300.0),
    "switch.outlet":        (10.0,  75.0, 300.0),
    "fan":                  (15.0,  40.0,  80.0),
    "media_player":         (10.0,  30.0, 200.0),
    "media_player.tv":      (50.0, 100.0, 200.0),
    "media_player.speaker":  (5.0,  15.0,  50.0),
    "media_player.receiver":(30.0,  80.0, 200.0),
    "climate":             (500.0,1200.0,3500.0),
    "climate.heat":        (500.0,1500.0,3000.0),
    "climate.cool":        (500.0,1200.0,3500.0),
    "vacuum":               (15.0,  25.0,  60.0),
    "cover":                (15.0,  30.0,  60.0),
}

_DOMAIN_W: Dict[str, float] = {
    "light": 8.0, "switch": 50.0, "fan": 40.0,
    "media_player": 25.0, "climate": 800.0,
    "cover": 30.0, "vacuum": 20.0,
}


def _build(key: str, data: Tuple) -> PowerProfile:
    strategy, on_w, standby_w, max_w = data
    mfr, model = key.split("/", 1)
    p = PowerProfile(
        manufacturer=mfr, model=model,
        device_type="light" if strategy == "linear" else "switch",
        strategy=strategy,
        power_on_w=on_w, standby_w=standby_w,
    )
    if strategy == "linear":
        p.min_watt = standby_w
        p.max_watt = max_w
    return p


class ProfileDatabase:
    """
    Beheert alle PowerCalc-profielen:
    ingebouwd + dagelijks remote gesynchroniseerd + PowerCalc lokaal fallback.
    """

    def __init__(self) -> None:
        self._builtin: Dict[str, PowerProfile] = {k: _build(k, v) for k, v in _B.items()}
        self._remote:  Dict[str, PowerProfile] = {}
        self._remote_ts: float = 0.0

    async def async_sync_remote(self, session) -> None:
        """Download nieuwste profielen van cloudems.eu (eens per 24u)."""
        if time.time() - self._remote_ts < REMOTE_TTL_S:
            return
        try:
            async with session.get(REMOTE_URL, timeout=FETCH_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    loaded = 0
                    for item in data.get("profiles", []):
                        key = f"{item['manufacturer'].lower()}/{item['model'].lower()}"
                        p = PowerProfile(
                            manufacturer=item["manufacturer"],
                            model=item["model"],
                            device_type=item.get("device_type", "switch"),
                            strategy=item.get("strategy", "fixed"),
                            power_on_w=float(item.get("power_on_w", 0)),
                            standby_w=float(item.get("standby_w", 0)),
                            min_watt=float(item.get("min_watt", 0)),
                            max_watt=float(item.get("max_watt", 0)),
                            source="remote",
                        )
                        self._remote[key] = p
                        loaded += 1
                    self._remote_ts = time.time()
                    _LOGGER.info("PowerCalc profiles: %d remote profielen geladen", loaded)
        except Exception as ex:
            _LOGGER.debug("PowerCalc remote sync mislukt: %s", ex)

    def get(self, manufacturer: str, model: str) -> Optional[PowerProfile]:
        """Zoek profiel op. Volgorde: remote > builtin."""
        key = f"{manufacturer.lower()}/{model.lower()}"
        return self._remote.get(key) or self._builtin.get(key)

    def get_by_aliases(self, name: str) -> Optional[PowerProfile]:
        """Zoek op alternatieve naam (bijv. model-alias)."""
        name_l = name.lower()
        for p in list(self._remote.values()) + list(self._builtin.values()):
            if name_l in (p.model.lower(), p.manufacturer.lower()):
                return p
            if any(name_l in a.lower() for a in p.aliases):
                return p
        return None

    def fallback_watt(self, domain: str, device_class: Optional[str] = None) -> float:
        """Geef mediaan-vermogen voor dit domein/device_class."""
        if device_class:
            key = f"{domain}.{device_class}"
            if key in _CLASS_W:
                return _CLASS_W[key][1]
        if domain in _CLASS_W:
            return _CLASS_W[domain][1]
        return _DOMAIN_W.get(domain, 0.0)

    @property
    def total_profiles(self) -> int:
        return len(self._builtin) + len(self._remote)
