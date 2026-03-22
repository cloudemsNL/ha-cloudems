# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS TTF Gas Price Fetcher — v1.0.0

Haalt de TTF Day-Ahead gasprijs op en rekent om naar all-in consumentenprijs.

Volgorde gasprijs bepaling:
  1. Geconfigureerde HA sensor (gas_price_sensor)  → direct all-in, geen omrekening
  2. Handmatige TTF sensor    (gas_ttf_sensor)     → spot excl. BTW → omrekenen
  3. TTF Day-Ahead via EnergyZero API (NL, gratis) → spot excl. BTW → omrekenen
  4. Vaste handmatige prijs   (gas_price_fixed)    → direct all-in

Omrekening TTF spot → all-in (alle componenten uit tariffs.json via TariffFetcher):
  all_in = (ttf_spot + opslag + netbeheer_var + eb + ode) × (1 + btw)

Geen hardcoded tarieven — alles via TariffFetcher → tariffs.json → fallback dict.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Cache: TTF Day-Ahead wordt rond 12:00 gepubliceerd voor volgende dag
TTF_CACHE_SECONDS = 3600 * 4   # 4 uur

# EnergyZero API — gratis NL gas day-ahead (excl. BTW)
_ENERGYZERO_GAS_URL = (
    "https://api.energyzero.nl/v1/energyprices"
    "?fromDate={from_date}&tillDate={till_date}"
    "&interval=4&usageType=3&inclBtw=false"
)


class TTFGasFetcher:
    """Haalt TTF Day-Ahead gasprijs op en rekent om naar all-in consumentenprijs."""

    def __init__(self, session, config: dict, tariff_fetcher=None) -> None:
        self._session         = session
        self._config          = config
        self._tariff_fetcher  = tariff_fetcher  # TariffFetcher instantie
        self._cache_ttf:      Optional[float] = None
        self._cache_all_in:   Optional[float] = None
        self._cache_ts:       float           = 0.0
        self._last_source:    str             = "none"
        self._last_components: dict           = {}

    # ── Publieke interface ─────────────────────────────────────────────────────

    @property
    def last_source(self) -> str:
        return self._last_source

    @property
    def ttf_spot_eur_m3(self) -> Optional[float]:
        return self._cache_ttf

    async def async_get_gas_price(self, hass) -> float:
        """
        Geef all-in gasprijs in €/m³.

        Volgorde:
          1. HA sensor (gas_price_sensor) — direct all-in
          2. Handmatige TTF sensor (gas_ttf_sensor) — spot → omrekenen
          3. TTF Day-Ahead via EnergyZero API — spot → omrekenen
          4. Vaste geconfigureerde prijs (gas_price_fixed)
        """
        import time

        # ── 1. Geconfigureerde all-in sensor ──────────────────────────────────
        sensor_eid = self._config.get("gas_price_sensor", "")
        if sensor_eid:
            st = hass.states.get(sensor_eid)
            if st and st.state not in ("unavailable", "unknown", "", None):
                try:
                    price = float(st.state)
                    self._last_source = "sensor"
                    _LOGGER.debug("TTFGasFetcher: sensor %s → %.4f €/m³", sensor_eid, price)
                    return price
                except (ValueError, TypeError):
                    pass

        # ── 2. Handmatige TTF sensor (spot excl. BTW) ─────────────────────────
        ttf_spot = None
        ttf_eid = self._config.get("gas_ttf_sensor", "")
        if ttf_eid:
            st2 = hass.states.get(ttf_eid)
            if st2 and st2.state not in ("unavailable", "unknown", ""):
                try:
                    ttf_spot = float(st2.state)
                    _LOGGER.debug("TTFGasFetcher: TTF sensor %s → %.4f €/m³", ttf_eid, ttf_spot)
                except (ValueError, TypeError):
                    pass

        # ── 3. TTF via EnergyZero API (cache 4u) ──────────────────────────────
        use_ttf = self._config.get("gas_use_ttf", True)
        if ttf_spot is None and use_ttf:
            now = time.time()
            if self._cache_all_in is not None and (now - self._cache_ts) < TTF_CACHE_SECONDS:
                self._last_source = "ttf_cached"
                return self._cache_all_in
            ttf_spot = await self._fetch_ttf_energyzero()

        # ── Omrekenen als we een spot prijs hebben ────────────────────────────
        if ttf_spot is not None:
            all_in, components = self._ttf_to_all_in(ttf_spot)
            self._cache_ttf       = ttf_spot
            self._cache_all_in    = all_in
            self._cache_ts        = time.time()
            self._last_source     = "ttf"
            self._last_components = components
            _LOGGER.info(
                "TTFGasFetcher: TTF spot=%.4f → all-in=%.4f €/m³ "
                "(eb=%.5f ode=%.5f nb=%.4f opslag=%.4f btw=%.0f%% bron=%s)",
                ttf_spot, all_in,
                components["eb"], components["ode"],
                components["netbeheer"], components["opslag"],
                components["btw"] * 100,
                components["tariff_source"],
            )
            return all_in

        # ── 4. Vaste prijs fallback ───────────────────────────────────────────
        fixed = float(self._config.get("gas_price_fixed") or
                      self._config.get("gas_price_eur_m3") or 1.25)
        self._last_source = "fixed"
        _LOGGER.debug("TTFGasFetcher: vaste prijs %.4f €/m³", fixed)
        return fixed

    def get_status(self) -> dict:
        """Status voor sensor/diagnostiek."""
        import time
        age = round((time.time() - self._cache_ts) / 60) if self._cache_ts else None
        return {
            "source":           self._last_source,
            "ttf_spot_eur_m3":  round(self._cache_ttf, 4) if self._cache_ttf else None,
            "all_in_eur_m3":    round(self._cache_all_in, 4) if self._cache_all_in else None,
            "cache_age_min":    age,
            "components":       self._last_components,
        }

    # ── Interne helpers ────────────────────────────────────────────────────────

    async def _fetch_ttf_energyzero(self) -> Optional[float]:
        """Haal TTF Day-Ahead prijs op via EnergyZero API (NL, gratis, excl. BTW)."""
        if not self._session:
            return None
        try:
            now     = datetime.now(tz=timezone.utc)
            from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            till_dt = from_dt + timedelta(days=1)
            url = _ENERGYZERO_GAS_URL.format(
                from_date=from_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                till_date=till_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            )
            async with self._session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    _LOGGER.debug("TTFGasFetcher: EnergyZero HTTP %d", resp.status)
                    return None
                data   = await resp.json()
                prices = data.get("Prices", [])
                values = [float(p["price"]) for p in prices if p.get("price") is not None]
                if not values:
                    return None
                return round(sum(values) / len(values), 6)
        except Exception as err:
            _LOGGER.debug("TTFGasFetcher: EnergyZero fout: %s", err)
            return None

    def _ttf_to_all_in(self, ttf_excl_btw: float) -> tuple[float, dict]:
        """
        Reken TTF spot (excl. BTW, €/m³) om naar all-in.

        Alle componenten via TariffFetcher → tariffs.json → fallback dict.
        Retourneert (all_in_prijs, componenten_dict).
        """
        country      = self._config.get("gas_country",      "NL")
        supplier_key = self._config.get("gas_supplier",     "none")
        netbeheerder = self._config.get("gas_netbeheerder", "default")

        if self._tariff_fetcher is not None:
            t = self._tariff_fetcher.get_gas_tariffs(country, supplier_key, netbeheerder)
        else:
            # TariffFetcher niet beschikbaar — gebruik fallback uit tariff_fetcher module
            from ..tariff_fetcher import (
                _GAS_EB_FALLBACK, _GAS_NETBEHEER_FALLBACK, _GAS_MARKUP_FALLBACK
            )
            year = datetime.now().year
            country_fb = _GAS_EB_FALLBACK.get(country, _GAS_EB_FALLBACK.get("NL", {}))
            candidates = {y: v for y, v in country_fb.items() if y <= year}
            yr = candidates.get(max(candidates)) if candidates else {}
            nb_map = _GAS_NETBEHEER_FALLBACK.get(country, {})
            gm_map = _GAS_MARKUP_FALLBACK.get(country, {})
            t = {
                "eb_eur_m3":        yr.get("eb",  0.29338),
                "ode_eur_m3":       yr.get("ode", 0.00494),
                "btw":              yr.get("btw", 0.21),
                "netbeheer_eur_m3": nb_map.get(netbeheerder) or nb_map.get("default") or 0.10,
                "markup_eur_m3":    gm_map.get(supplier_key) or gm_map.get("default") or 0.05,
                "source":           "fallback",
            }

        eb        = t["eb_eur_m3"]
        ode       = t["ode_eur_m3"]
        netbeheer = t["netbeheer_eur_m3"]
        opslag    = t["markup_eur_m3"]
        btw       = t["btw"]

        excl_btw = ttf_excl_btw + opslag + netbeheer + eb + ode
        all_in   = round(excl_btw * (1 + btw), 4)

        components = {
            "ttf_spot":      round(ttf_excl_btw, 6),
            "eb":            round(eb,            5),
            "ode":           round(ode,           5),
            "netbeheer":     round(netbeheer,     4),
            "opslag":        round(opslag,        4),
            "btw":           btw,
            "excl_btw_sum":  round(excl_btw,      4),
            "tariff_source": t.get("source", "?"),
        }
        return all_in, components
