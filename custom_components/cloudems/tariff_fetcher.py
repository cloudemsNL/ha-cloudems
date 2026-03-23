# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""
CloudEMS Tariff Fetcher  v1.0.0

Haalt actuele energiebelasting (EB) en leveranciersopslag op uit
officiële bronnen en leert ze uit historische betaalde prijzen.

Bronnen (prioriteitsvolgorde):
  1. Zelfgeleerd uit (epex_base, paid_price) paren — meest nauwkeurig
  2. CBS Statline Open Data API — officiële NL energiebelasting
  3. Ingebouwde fallback per jaar — nooit stale hardcode

Opslag: HA Storage (cloudems_tariff_fetcher_v1)
  - Persistent over herstarts
  - 7 dagen cache voor CBS data
  - Markup samples bewaard over sessies

Gebruik in coordinator:
    self._tariff_fetcher = TariffFetcher(hass, session_getter, config)
    await self._tariff_fetcher.async_setup()
    eb, markup, btw, source = self._tariff_fetcher.get_tariffs(country, supplier_key)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY    = "cloudems_tariff_fetcher_v1"
STORAGE_VER    = 1
CBS_CACHE_TTL  = 7 * 86400      # 7 dagen
LEARN_MIN_PAIRS = 12            # minimaal aantal paren voor activatie leren
LEARN_MAX_PAIRS = 500

# ── Fallback EB per jaar per land (excl. BTW, eerste schijf) ─────────────────
# Bronnen: Belastingdienst.nl tarieven energiebelasting
# Formule: incl_BTW / 1.21 = excl_BTW
# Wordt ALLEEN gebruikt als CloudEMS JSON, CBS API en leren alle drie falen.
_EB_FALLBACK: dict[str, dict[int, float]] = {
    "NL": {
        2022: 0.09217,   # 0.1115 incl. BTW / 1.21
        2023: 0.12599,   # 0.1525 incl. BTW / 1.21
        2024: 0.12599,   # 0.1525 incl. BTW / 1.21
        2025: 0.10153,   # 0.1229 incl. BTW / 1.21 (verlaging per 1-1-2025)
        2026: 0.09157,   # 0.1108 incl. BTW / 1.21 (verlaging per 1-1-2026)
    },
    "BE": {
        2024: 0.0,       # BE heeft geen directe EB vergelijkbaar
        2025: 0.0,
        2026: 0.0,
    },
    "DE": {
        2024: 0.02050,   # Stromsteuer Niederspannung
        2025: 0.02050,
        2026: 0.02050,
    },
    "FR": {
        2024: 0.02230,   # TICFE basis
        2025: 0.05000,   # stapsgewijze herinvoering
        2026: 0.05000,
    },
}


# ── Gas fallback tarieven per jaar per land (excl. BTW, per m³) ───────────────
# Bron: Belastingdienst.nl / RVO / Europese Commissie
# Wordt ALLEEN gebruikt als tariffs.json (GitHub + lokaal) niet bereikbaar is.
# Jaarlijks updaten in tariffs.json — dit is de laatste verdedigingslinie.
_GAS_EB_FALLBACK: dict[str, dict[int, dict[str, float]]] = {
    "NL": {
        # Energiebelasting schijf 1 (0–1500 m³/jaar) + ODE gas
        2024: {"eb": 0.33227, "ode": 0.00397, "btw": 0.21},
        2025: {"eb": 0.29338, "ode": 0.00494, "btw": 0.21},
        2026: {"eb": 0.29338, "ode": 0.00494, "btw": 0.21},
    },
    "BE": {
        # BE: geen directe EB op gas voor huishoudens
        2025: {"eb": 0.0, "ode": 0.0, "btw": 0.06},
        2026: {"eb": 0.0, "ode": 0.0, "btw": 0.06},
    },
    "DE": {
        # Erdgassteuer (per m³ bij 10 kWh/m³)
        2025: {"eb": 0.00553, "ode": 0.0, "btw": 0.19},
        2026: {"eb": 0.00553, "ode": 0.0, "btw": 0.19},
    },
}

# Netbeheer variabele kosten gas (€/m³ excl. BTW) — fallback
_GAS_NETBEHEER_FALLBACK: dict[str, dict[str, float]] = {
    "NL": {
        "liander":  0.1012, "stedin":   0.0987, "enexis":   0.1034,
        "rendo":    0.0945, "westland": 0.0912, "default":  0.1000,
    },
}

# Leveranciersopslag gas (€/m³ excl. BTW) — fallback
_GAS_MARKUP_FALLBACK: dict[str, dict[str, float]] = {
    "NL": {
        "vattenfall": 0.0550, "eneco": 0.0480, "essent": 0.0520,
        "greenchoice": 0.0440, "budget": 0.0380, "pure": 0.0420,
        "anwb": 0.0460, "none": 0.0, "custom": 0.0, "default": 0.0500,
    },
}

# CloudEMS hosted tariff JSON — primaire bron voor automatische updates
# Jullie hoeven alleen dit bestand op GitHub te updaten elk jaar januari
CLOUDEMS_TARIFF_URL = (
    "https://raw.githubusercontent.com/cloudemsNL/ha-cloudems/main/tariffs.json"
)
CLOUDEMS_TARIFF_TTL = 7 * 86400   # 7 dagen cache

# BTW per land — dit wijzigt zelden
_VAT: dict[str, float] = {
    "NL": 0.21,
    "BE": 0.21,
    "DE": 0.19,
    "FR": 0.20,
}

# Standaard leveranciersopslag (€/kWh excl. BTW) — fallback
# Worden overschreven door leren
_MARKUP_DEFAULT: dict[str, dict[str, float]] = {
    "NL": {
        "vattenfall":  0.0215,
        "eneco":       0.0189,
        "essent":      0.0201,
        "greenchoice": 0.0175,
        "budget":      0.0165,
        "vandebron":   0.0182,
        "tibber":      0.0149,
        "zonneplan":   0.0169,
        "none":        0.0,
        "custom":      0.0,
    },
    "BE": {
        "engie":  0.0220, "luminus": 0.0210,
        "fluvius": 0.0180, "octa": 0.0195,
        "bolt": 0.0168, "none": 0.0, "custom": 0.0,
    },
    "DE": {
        "eon": 0.0250, "rwe": 0.0230, "ewe": 0.0220,
        "vattenfall": 0.0215, "tibber": 0.0160,
        "ostrom": 0.0145, "awattar": 0.0050,
        "none": 0.0, "custom": 0.0,
    },
    "FR": {
        "edf": 0.0200, "total": 0.0210,
        "engie_fr": 0.0195, "octopus_fr": 0.0155,
        "none": 0.0, "custom": 0.0,
    },
}


class TariffFetcher:
    """
    Single source of truth voor energiebelasting, BTW en leveranciersopslag.

    Prioriteit voor energiebelasting:
      1. Zelfgeleerd via paid_price – epex_base
      2. CBS Statline API (NL) — gecached 7 dagen
      3. Fallback tabel op jaar

    Prioriteit voor leveranciersopslag:
      1. Zelfgeleerd via paid_price – epex_base – eb
      2. Hardcoded fallback per leverancier
    """

    def __init__(self, hass, session_getter, config: dict) -> None:
        self._hass          = hass
        self._session_getter = session_getter   # callable → ClientSession
        self._config        = config
        self._store         = Store(hass, STORAGE_VER, STORAGE_KEY)

        # CBS cache
        self._cbs_eb: dict[str, float]  = {}   # country → EB €/kWh
        self._cbs_fetched_at: float     = 0.0
        self._json_markup: dict[str, dict[str, float]] = {}  # uit tariffs.json / GitHub
        self._json_gas_tax:       dict[str, dict] = {}
        self._json_gas_netbeheer: dict[str, dict] = {}
        self._json_gas_markup:    dict[str, dict] = {}

        # Leren uit (epex, paid) paren — persistente lijst
        # Structuur: {"NL:zonneplan": {"pairs": [(epex, paid), ...], "result": float|None}}
        self._learn_data: dict[str, dict] = {}

        self._ready = False

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Laad gecachte data uit storage en probeer CBS op te halen."""
        try:
            saved = await self._store.async_load() or {}
            self._cbs_eb           = saved.get("cbs_eb", {})
            self._cbs_fetched_at   = float(saved.get("cbs_fetched_at", 0))
            self._learn_data       = saved.get("learn_data", {})
            self._json_markup      = saved.get("json_markup", {})
            self._json_gas_tax       = saved.get("json_gas_tax", {})
            self._json_gas_netbeheer = saved.get("json_gas_netbeheer", {})
            self._json_gas_markup    = saved.get("json_gas_markup", {})
            _LOGGER.debug("TariffFetcher: geladen uit storage (%d leer-keys)", len(self._learn_data))
        except Exception as exc:
            _LOGGER.warning("TariffFetcher: storage laden mislukt: %s", exc)

        await self._maybe_refresh_cbs()
        self._ready = True

    async def async_save(self) -> None:
        """Sla huidige staat op in HA Storage."""
        try:
            await self._store.async_save({
                "cbs_eb":         self._cbs_eb,
                "cbs_fetched_at": self._cbs_fetched_at,
                "learn_data":     self._learn_data,
                "json_markup":    self._json_markup,
                "json_gas_tax":       self._json_gas_tax,
                "json_gas_netbeheer": self._json_gas_netbeheer,
                "json_gas_markup":    self._json_gas_markup,
            })
        except Exception as exc:
            _LOGGER.warning("TariffFetcher: opslaan mislukt: %s", exc)

    # ── Publieke API ──────────────────────────────────────────────────────────

    def get_tariffs(
        self,
        country: str,
        supplier_key: str,
        custom_markup: float = 0.0,
    ) -> Tuple[float, float, float, str]:
        """
        Geef (eb_eur_kwh, markup_eur_kwh, vat_rate, source_label).

        source_label: 'learned' | 'cbs' | 'fallback'
        """
        vat = _VAT.get(country, 0.21)
        eb, markup, source = self._resolve_eb_and_markup(country, supplier_key, custom_markup)
        return eb, markup, vat, source

    def get_gas_tariffs(
        self,
        country: str,
        supplier_key: str = "default",
        netbeheerder: str = "default",
    ) -> dict:
        """
        Geef gas belastingcomponenten (excl. BTW, per m³).

        Volgorde:
          1. tariffs.json geladen via GitHub / lokaal bestand
          2. Hardcoded _GAS_EB_FALLBACK (laatste verdedigingslinie)

        Retourneert dict met:
          eb_eur_m3, ode_eur_m3, netbeheer_eur_m3,
          markup_eur_m3, btw, source
        """
        year = datetime.now().year
        source = "fallback"

        # ── Stap 1: tariffs.json (geladen via _fetch_cloudems_json / _fetch_local_json) ──
        gas_tax = self._json_gas_tax.get(country, {}) if hasattr(self, '_json_gas_tax') else {}
        if gas_tax:
            yr_data = gas_tax.get(str(year)) or gas_tax.get(str(year - 1)) or {}
            if yr_data:
                source = "json"
        else:
            yr_data = {}

        # ── Stap 2: hardcoded fallback ────────────────────────────────────────
        if not yr_data:
            country_fb = _GAS_EB_FALLBACK.get(country, _GAS_EB_FALLBACK.get("NL", {}))
            candidates = {y: v for y, v in country_fb.items() if y <= year}
            yr_data = candidates.get(max(candidates)) if candidates else {}
            if yr_data:
                source = "fallback"

        eb      = float(yr_data.get("eb",  0.29338))
        ode     = float(yr_data.get("ode", 0.00494))
        btw     = float(yr_data.get("btw", 0.21))

        # Netbeheer
        json_nb = self._json_gas_netbeheer.get(country, {}) if hasattr(self, '_json_gas_netbeheer') else {}
        nb_map  = json_nb or _GAS_NETBEHEER_FALLBACK.get(country, {})
        netbeheer = float(nb_map.get(netbeheerder) or nb_map.get("default") or 0.10)

        # Leveranciersopslag
        json_gm  = self._json_gas_markup.get(country, {}) if hasattr(self, '_json_gas_markup') else {}
        gm_map   = json_gm or _GAS_MARKUP_FALLBACK.get(country, {})
        markup   = float(gm_map.get(supplier_key) or gm_map.get("default") or 0.05)

        _LOGGER.debug(
            "TariffFetcher gas [%s/%s] bron=%s eb=%.5f ode=%.5f nb=%.4f opslag=%.4f btw=%.0f%%",
            country, year, source, eb, ode, netbeheer, markup, btw * 100,
        )
        return {
            "eb_eur_m3":        eb,
            "ode_eur_m3":       ode,
            "netbeheer_eur_m3": netbeheer,
            "markup_eur_m3":    markup,
            "btw":              btw,
            "source":           source,
        }

    def add_price_pair(
        self,
        country: str,
        supplier_key: str,
        epex_eur_kwh: float,
        paid_eur_kwh: float,
        include_tax: bool,
        include_btw: bool,
    ) -> None:
        """
        Voeg een (epex, paid) paar toe voor het lerende systeem.

        paid_eur_kwh is de werkelijk betaalde prijs (all-in of excl. BTW,
        afhankelijk van de bron-sensor). include_tax/include_btw geeft aan
        wat er al in zit.
        """
        if not (0.001 <= epex_eur_kwh <= 1.0):
            return
        if not (0.01 <= paid_eur_kwh <= 3.0):
            return

        key = f"{country}:{supplier_key}"
        if key not in self._learn_data:
            self._learn_data[key] = {"pairs": [], "result": None}

        entry = self._learn_data[key]
        entry["pairs"].append({
            "epex":        round(epex_eur_kwh, 5),
            "paid":        round(paid_eur_kwh, 5),
            "include_tax": include_tax,
            "include_btw": include_btw,
            "ts":          int(time.time()),
        })
        # Bewaar laatste N paren
        if len(entry["pairs"]) > LEARN_MAX_PAIRS:
            entry["pairs"] = entry["pairs"][-LEARN_MAX_PAIRS:]

        # Herbereken als genoeg data
        if len(entry["pairs"]) >= LEARN_MIN_PAIRS:
            self._recompute_learned(key, country)

    def get_learned_result(self, country: str, supplier_key: str) -> Optional[dict]:
        """Geef geleerde waarden terug, of None als nog niet beschikbaar."""
        key = f"{country}:{supplier_key}"
        entry = self._learn_data.get(key, {})
        return entry.get("result")

    def get_eb_source(self, country: str) -> str:
        """Geef aan wat de bron is van de huidige EB waarde."""
        if self._cbs_eb.get(country) is not None:
            age_h = (time.time() - self._cbs_fetched_at) / 3600
            return f"CBS Statline (gecached {age_h:.0f}u geleden)"
        year = datetime.now().year
        return f"Fallback tabel {year}"

    # ── Interne logica ────────────────────────────────────────────────────────

    def _resolve_eb_and_markup(
        self, country: str, supplier_key: str, custom_markup: float
    ) -> Tuple[float, float, str]:
        """Geef (eb, markup, source) terug op basis van beste beschikbare data."""

        key = f"{country}:{supplier_key}"
        learned = self._learn_data.get(key, {}).get("result")

        if learned and learned.get("n", 0) >= LEARN_MIN_PAIRS:
            # Zelfgeleerd — meest nauwkeurig
            eb_learned     = learned.get("eb_eur_kwh")
            markup_learned = learned.get("markup_eur_kwh")
            if eb_learned is not None and markup_learned is not None:
                return eb_learned, markup_learned, "learned"

        # CBS API data voor EB
        eb = self._cbs_eb.get(country)
        cbs_ok = eb is not None
        if not cbs_ok:
            year = datetime.now().year
            eb = self._get_fallback_eb(country, year)

        # Markup: JSON (GitHub/lokaal) heeft voorrang op hardcoded tabel
        if supplier_key == "custom":
            markup = custom_markup
        else:
            json_markups = self._json_markup.get(country, {})
            markup = json_markups.get(supplier_key,
                     _MARKUP_DEFAULT.get(country, {}).get(supplier_key, 0.0))

        source = "cbs" if cbs_ok else "fallback"
        return eb, markup, source

    def _get_fallback_eb(self, country: str, year: int) -> float:
        """Meest actuele bekende EB voor dit land en jaar."""
        table = _EB_FALLBACK.get(country, {})
        if not table:
            return 0.0
        # Gebruik het gegeven jaar, of het laatste bekende jaar
        if year in table:
            return table[year]
        # Neem het dichtstbijzijnde lagere jaar
        candidates = [y for y in sorted(table.keys()) if y <= year]
        return table[candidates[-1]] if candidates else 0.0

    def _recompute_learned(self, key: str, country: str) -> None:
        """
        Bereken geleerde EB + markup uit opgeslagen paren.

        Methode: mediaan van (paid_excl_btw - epex) per paar.
        Split in EB + markup is lastig zonder extra info, dus we leren
        de gecombineerde 'opslag' (EB + markup) als één getal.
        Vergelijk dan met CBS/fallback EB om markup te isoleren.
        """
        entry  = self._learn_data[key]
        pairs  = entry["pairs"]
        vat    = _VAT.get(country, 0.21)

        implied_opslagen = []
        for p in pairs:
            epex   = p["epex"]
            paid   = p["paid"]
            inc_btw = p.get("include_btw", True)

            # Normaliseer paid naar excl. BTW
            paid_excl_btw = paid / (1 + vat) if inc_btw else paid

            opslag = paid_excl_btw - epex
            if -0.02 <= opslag <= 0.35:   # sanity: -2 ct tot 35 ct
                implied_opslagen.append(opslag)

        if len(implied_opslagen) < LEARN_MIN_PAIRS:
            return

        sorted_op = sorted(implied_opslagen)
        median_op = sorted_op[len(sorted_op) // 2]

        # Probeer EB te isoleren via CBS of fallback
        year = datetime.now().year
        eb_ref = self._cbs_eb.get(country) or self._get_fallback_eb(country, year)

        markup_learned = max(0.0, median_op - eb_ref)

        # Sanity check: markup mag niet groter zijn dan totale opslag
        if markup_learned > median_op:
            markup_learned = 0.0
            eb_learned = median_op
        else:
            eb_learned = eb_ref  # vertrouw CBS/fallback voor EB

        entry["result"] = {
            "eb_eur_kwh":     round(eb_learned, 5),
            "markup_eur_kwh": round(markup_learned, 5),
            "combined_eur_kwh": round(median_op, 5),
            "n":              len(implied_opslagen),
            "updated_at":     int(time.time()),
        }
        _LOGGER.info(
            "TariffFetcher [%s]: geleerd — EB %.5f + markup %.5f = %.5f €/kWh (%d paren)",
            key, eb_learned, markup_learned, median_op, len(implied_opslagen),
        )

    # ── Tarieven ophalen: CloudEMS JSON → CBS Statline → fallback tabel ──────

    async def _maybe_refresh_cbs(self) -> None:
        """Ververs tariefdata als cache verlopen is.

        Volgorde:
          1. CloudEMS hosted JSON op GitHub — jullie updaten dit elk jaar januari
          2. CBS Statline OData API — officiële NL backup
          3. Hardcoded fallback tabel — noodgeval, nooit stale
        """
        age = time.time() - self._cbs_fetched_at
        if age < CLOUDEMS_TARIFF_TTL and self._cbs_eb.get("NL") is not None:
            _LOGGER.debug("TariffFetcher: cache nog geldig (%.0f s oud)", age)
            return
        if await self._fetch_cloudems_json():
            return
        await self._fetch_cbs_nl()
        # Als CBS ook faalt, probeer het lokale tariffs.json uit de installatie
        if not self._cbs_eb.get("NL"):
            await self._fetch_local_json()

    async def _fetch_local_json(self) -> None:
        """
        Lees tarieven uit het meegeleverde tariffs.json in de installatiemap.

        Dit bestand zit in de root van de zip naast custom_components/.
        Gebruikt als GitHub én CBS beide niet bereikbaar zijn.
        HA geeft de integratiemap via __file__ van dit module.
        """
        import json
        import os
        try:
            # tariffs.json zit twee niveaus omhoog: cloudems/ → custom_components/ → root
            integration_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            local_path = os.path.join(integration_dir, "tariffs.json")
            if not os.path.isfile(local_path):
                _LOGGER.debug("TariffFetcher lokaal: %s niet gevonden", local_path)
                return
            with open(local_path, encoding="utf-8") as f:
                data = json.load(f)
            year = str(datetime.now().year)
            tax_data = data.get("energy_tax", {})
            updated = False
            for country, years in tax_data.items():
                if year in years:
                    eb_eur = float(years[year])
                else:
                    candidates = {int(y): v for y, v in years.items() if int(y) <= int(year)}
                    if not candidates:
                        continue
                    eb_eur = float(candidates[max(candidates)])
                if 0.0 <= eb_eur <= 0.25:
                    self._cbs_eb[country] = eb_eur
                    updated = True
                    _LOGGER.info(
                        "TariffFetcher lokaal: %s EB %.5f €/kWh (jaar %s, bestand: %s)",
                        country, eb_eur, year, data.get("updated", "?"),
                    )
            # Laad ook supplier_markup uit lokale JSON
            markup_data = data.get("supplier_markup", {})
            if markup_data and not self._json_markup:
                self._json_markup = markup_data
                _LOGGER.debug("TariffFetcher lokaal: markups geladen voor %s", list(markup_data.keys()))
                updated = True

            # Gas tarieven laden
            gas_tax = data.get("gas_tax", {})
            if gas_tax and not self._json_gas_tax:
                self._json_gas_tax = gas_tax
                _LOGGER.debug("TariffFetcher lokaal: gas_tax geladen voor %s", list(gas_tax.keys()))
                updated = True
            gas_nb = data.get("gas_netbeheer", {})
            if gas_nb and not self._json_gas_netbeheer:
                self._json_gas_netbeheer = gas_nb
                updated = True
            gas_mk = data.get("gas_supplier_markup", {})
            if gas_mk and not self._json_gas_markup:
                self._json_gas_markup = gas_mk
                updated = True

            if updated:
                self._cbs_fetched_at = time.time()
                await self.async_save()
        except Exception as exc:
            _LOGGER.debug("TariffFetcher lokaal: lezen mislukt: %s", exc)

    async def _fetch_cloudems_json(self) -> bool:
        """
        Haal tarieven op uit CloudEMS hosted JSON op GitHub.

        tariffs.json formaat:
        {
          "energy_tax": {
            "NL": {"2025": 0.10153, "2026": 0.09157, "2027": 0.09500},
            "BE": {"2025": 0.0},
            "DE": {"2025": 0.02050}
          },
          "updated": "2026-01-01"
        }

        Elk jaar januari alleen tariffs.json updaten op GitHub —
        geen code-aanpassing, geen nieuwe release nodig.
        """
        try:
            session = self._session_getter()
            async with session.get(CLOUDEMS_TARIFF_URL, timeout=8) as resp:
                if resp.status != 200:
                    _LOGGER.debug("TariffFetcher CloudEMS JSON: HTTP %d", resp.status)
                    return False
                data = await resp.json(content_type=None)
                year = str(datetime.now().year)
                tax_data = data.get("energy_tax", {})
                updated = False
                for country, years in tax_data.items():
                    if year in years:
                        eb_eur = float(years[year])
                    else:
                        candidates = {int(y): v for y, v in years.items() if int(y) <= int(year)}
                        if not candidates:
                            continue
                        eb_eur = float(candidates[max(candidates)])
                    if 0.0 <= eb_eur <= 0.25:  # sanity: 0–25 ct/kWh excl. BTW
                        self._cbs_eb[country] = eb_eur
                        updated = True
                        _LOGGER.info(
                            "TariffFetcher CloudEMS JSON: %s EB %.5f €/kWh (jaar %s, bestand: %s)",
                            country, eb_eur, year, data.get("updated", "?"),
                        )
                # Laad ook supplier_markup uit JSON
                markup_data = data.get("supplier_markup", {})
                if markup_data:
                    self._json_markup = markup_data
                    updated = True
                    _LOGGER.debug("TariffFetcher CloudEMS JSON: markups geladen voor %s", list(markup_data.keys()))

                # Gas tarieven laden
                gas_tax = data.get("gas_tax", {})
                if gas_tax:
                    self._json_gas_tax = gas_tax
                    updated = True
                    _LOGGER.debug("TariffFetcher CloudEMS JSON: gas_tax geladen voor %s", list(gas_tax.keys()))
                gas_nb = data.get("gas_netbeheer", {})
                if gas_nb:
                    self._json_gas_netbeheer = gas_nb
                    updated = True
                gas_mk = data.get("gas_supplier_markup", {})
                if gas_mk:
                    self._json_gas_markup = gas_mk
                    updated = True

                if updated:
                    self._cbs_fetched_at = time.time()
                    await self.async_save()
                    return True
                _LOGGER.debug("TariffFetcher CloudEMS JSON: geen bruikbare waarden")
                return False
        except Exception as exc:
            _LOGGER.debug("TariffFetcher CloudEMS JSON: ophalen mislukt: %s", exc)
            return False

    async def _fetch_cbs_nl(self) -> None:
        """
        Haal actuele NL EB op via CBS Statline OData API (backup).

        Tabel 70052NED: Belasting op leidingwater en energiebelasting
        Elektriciteit_2 = tarief eerste schijf in ct/kWh incl. BTW
        """
        url = (
            "https://opendata.cbs.nl/ODataApi/odata/70052NED/TypedDataSet"
            "?$filter=startswith(Perioden,'2025') or startswith(Perioden,'2026')"
            "&$select=Perioden,Elektriciteit_2"
            "&$orderby=Perioden desc"
            "&$top=4"
            "&$format=json"
        )
        try:
            session = self._session_getter()
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    _LOGGER.debug("TariffFetcher CBS: HTTP %d", resp.status)
                    return
                data = await resp.json(content_type=None)
                rows = data.get("value", [])
                if not rows:
                    _LOGGER.debug("TariffFetcher CBS: geen rijen ontvangen")
                    return
                vat_nl = _VAT.get("NL", 0.21)
                for row in rows:
                    raw = row.get("Elektriciteit_2")
                    periode = row.get("Perioden", "")
                    if raw is None:
                        continue
                    # CBS rapporteert in ct/kWh incl. BTW — omrekenen naar excl. BTW
                    eb_ct_incl = float(raw)
                    if 1.0 <= eb_ct_incl <= 25.0:
                        eb_eur_excl = round((eb_ct_incl / 100.0) / (1 + vat_nl), 5)
                        self._cbs_eb["NL"] = eb_eur_excl
                        self._cbs_fetched_at = time.time()
                        _LOGGER.info(
                            "TariffFetcher CBS: NL EB %.5f €/kWh excl. BTW (%.2f ct incl., periode: %s)",
                            eb_eur_excl, eb_ct_incl, periode,
                        )
                        await self.async_save()
                        return
                _LOGGER.debug("TariffFetcher CBS: geen bruikbare EB waarde in respons")
        except Exception as exc:
            _LOGGER.debug("TariffFetcher CBS: ophalen mislukt: %s", exc)
