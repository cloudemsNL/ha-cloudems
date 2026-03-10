# -*- coding: utf-8 -*-
"""
CloudEMS SalderingContext — v1.0.0

Gedeelde saldering-bewuste prijslogica voor alle batterij- en PV-modules.

De Nederlandse salderingsregeling (WEK) wordt stapsgewijs afgebouwd:
  2025 — 64%   (0.64 × inkoopprijs)
  2026 — 36%   (0.36 × inkoopprijs)
  2027 —  0%   (volledige afschaffing)

Impact op batterijbeslissingen:
  - Exportwaarde van ontladen ≠ inkoopprijs bij < 100% saldering
  - Arbitragespread = (verkoopprijs × saldering%) - laadprijs - cycluskosten
  - Ontladen naar net is bij lage saldering alleen rendabel bij grote spreads
  - Zelfconsumptie (huis dekt eigen last) levert altijd de volle inkoopprijs op

Gebruik:
    ctx = SalderingContext.for_current_year()
    spread = ctx.net_arbitrage_spread(buy_price=0.06, sell_price=0.28)
    worth_discharging = ctx.is_discharge_worthwhile(
        sell_price=0.28,
        house_load_w=1500,
        discharge_w=2500,
        cycle_cost_eur_kwh=0.03,
    )

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)

# Salderingspercentages per jaar (NL WEK, Staatsblad 2023)
SALDERING_SCHEDULE: dict[int, float] = {
    2023: 1.00,
    2024: 1.00,
    2025: 0.64,
    2026: 0.36,
    2027: 0.00,
}

# Minimum netto-spread om arbitrage de moeite waard te vinden (€/kWh)
# Dekt cyclusverliezen (~3%), omvormerverliezen (~5%), en minimale marge
MIN_ARBITRAGE_SPREAD_EUR = 0.04

# Geschatte cyclusdegradatiekosten per kWh (€/kWh geladen+ontladen)
# Gebaseerd op €700/kWh batterijprijs, 4000 cycli, 80% DoD
DEFAULT_CYCLE_COST_EUR_KWH = 0.044

# Omzetverliezen batterij (laden + ontladen round-trip)
BATTERY_ROUNDTRIP_EFFICIENCY = 0.90   # 90% round-trip


@dataclass
class SalderingContext:
    """
    Bevat alle saldering-gerelateerde berekeningen voor één kalenderjaar.

    Aangemaakt via SalderingContext.for_current_year() of for_year(year).
    """
    year:              int
    saldering_pct:     float    # 0.0 – 1.00  (fractie, niet percentage)
    cycle_cost_eur_kwh: float   # degradatiekosten per kWh doorvoer

    # ── Fabriek-methodes ───────────────────────────────────────────────────────

    @classmethod
    def for_current_year(cls, cycle_cost: float = DEFAULT_CYCLE_COST_EUR_KWH) -> "SalderingContext":
        """Maak context op basis van het huidige kalenderjaar."""
        year = datetime.now(timezone.utc).year
        return cls.for_year(year, cycle_cost)

    @classmethod
    def for_year(cls, year: int, cycle_cost: float = DEFAULT_CYCLE_COST_EUR_KWH) -> "SalderingContext":
        """Maak context voor een specifiek jaar."""
        # Jaren na 2027: 0% saldering
        pct = SALDERING_SCHEDULE.get(year, 0.0 if year > 2027 else 1.0)
        return cls(year=year, saldering_pct=pct, cycle_cost_eur_kwh=cycle_cost)

    # ── Kernberekeningen ───────────────────────────────────────────────────────

    def export_value_eur_kwh(self, import_price_eur_kwh: float) -> float:
        """
        Effectieve waarde van 1 kWh teruglevering aan het net (€/kWh).

        Bij 100% saldering: gelijk aan import_price (kWh voor kWh).
        Bij 36% saldering: 36% van import_price.
        Bij 0% saldering: spotmarktprijs (los doorgegeven via sell_price parameter).

        Voor pure Powerplay/Zonneplan-gebruikers: sell_price is de tariefprijs
        die Zonneplan uitkeert, niet de EPEX-spotprijs.
        """
        return round(import_price_eur_kwh * self.saldering_pct, 5)

    def net_arbitrage_spread(
        self,
        buy_price_eur_kwh: float,
        sell_price_eur_kwh: float,
    ) -> float:
        """
        Netto arbitragespread voor batterijcyclus (€/kWh).

        Formule:
            spread = (sell × saldering%) × roundtrip_eff - buy - cycle_cost

        Positief = winstgevend. Negatief = verliesgevend.

        Args:
            buy_price_eur_kwh:  prijs bij laden (goedkoop uur, EPEX of vast)
            sell_price_eur_kwh: prijs bij ontladen (duur uur, EPEX of tariefgroep)
        """
        effective_sell = sell_price_eur_kwh * self.saldering_pct
        net = (effective_sell * BATTERY_ROUNDTRIP_EFFICIENCY
               - buy_price_eur_kwh
               - self.cycle_cost_eur_kwh)
        return round(net, 5)

    def is_arbitrage_worthwhile(
        self,
        buy_price_eur_kwh: float,
        sell_price_eur_kwh: float,
        min_spread: float = MIN_ARBITRAGE_SPREAD_EUR,
    ) -> tuple[bool, str]:
        """
        Is een laad→ontlaad cyclus puur voor arbitrage (export) de moeite waard?

        Returns:
            (bool, reden)
        """
        spread = self.net_arbitrage_spread(buy_price_eur_kwh, sell_price_eur_kwh)
        if spread >= min_spread:
            return True, (
                f"Spread €{spread:.4f}/kWh ≥ drempel €{min_spread:.4f} "
                f"(saldering {self.saldering_pct:.0%}, jaar {self.year})"
            )
        return False, (
            f"Spread €{spread:.4f}/kWh < drempel €{min_spread:.4f} "
            f"(verkoop €{sell_price_eur_kwh:.4f} × {self.saldering_pct:.0%} "
            f"- inkoop €{buy_price_eur_kwh:.4f} - cycluskosten €{self.cycle_cost_eur_kwh:.4f})"
        )

    def discharge_value_eur_kwh(
        self,
        sell_price_eur_kwh: float,
        house_load_fraction: float = 0.0,
    ) -> float:
        """
        Effectieve waarde van 1 kWh ontladen (€/kWh).

        Splitst ontladen in twee delen:
          - Eigenverbruikdeel (house_load_fraction): bespaart volle inkoopprijs
          - Exportdeel (1 - house_load_fraction): krijgt saldering × inkoopprijs

        Args:
            sell_price_eur_kwh:   huidige prijs op het net (inkoopprijs als referentie)
            house_load_fraction:  fractie van ontlaadvermogen dat het huis direct verbruikt
                                  (0.0 = alles export, 1.0 = alles eigenverbruik)
        """
        house_fraction = max(0.0, min(1.0, house_load_fraction))
        export_fraction = 1.0 - house_fraction

        # Eigenverbruikdeel: bespaart altijd de volle importprijs (ongeacht saldering)
        eigenverbruik_value = house_fraction * sell_price_eur_kwh
        # Exportdeel: afhankelijk van salderingspercentage
        export_value = export_fraction * sell_price_eur_kwh * self.saldering_pct

        return round(eigenverbruik_value + export_value, 5)

    def min_discharge_price_for_profit(
        self,
        buy_price_eur_kwh: float,
        house_load_fraction: float = 0.0,
        min_spread: float = MIN_ARBITRAGE_SPREAD_EUR,
    ) -> float:
        """
        Minimale verkoopprijs (€/kWh) waarbij ontladen nog winstgevend is.

        Handig als drempel: als current_price < min_discharge_price → niet ontladen.
        """
        # eigenverbruikdeel bespaard altijd vol, exportdeel krijgt saldering%
        # We willen: discharge_value - buy_price - cycle_cost >= min_spread
        # house_frac × p + (1-house_frac) × p × sal_pct - buy - cycle >= min_spread
        # p × (house_frac + (1-house_frac)×sal_pct) >= buy + cycle + min_spread
        combined_factor = (
            house_load_fraction
            + (1.0 - house_load_fraction) * self.saldering_pct
        )
        if combined_factor <= 0:
            return float("inf")
        required = (buy_price_eur_kwh + self.cycle_cost_eur_kwh + min_spread) / combined_factor
        return round(required, 4)

    def is_discharge_worthwhile(
        self,
        sell_price_eur_kwh: float,
        house_load_w: float,
        discharge_w: float,
        buy_price_eur_kwh: float = 0.0,
        min_spread: float = MIN_ARBITRAGE_SPREAD_EUR,
    ) -> tuple[bool, str, float]:
        """
        Is ontladen nu winstgevend, rekening houdend met huidig huisverbruik?

        Berekent de eigenverbruikfractie op basis van house_load_w vs discharge_w.
        Eigenverbruik bespaart altijd de volle inkoopprijs, export krijgt saldering%.

        Args:
            sell_price_eur_kwh: huidige importprijs (wat je bespaart door eigen gebruik)
            house_load_w:       huidig huisverbruik (W) — hoeveel de batterij kan dekken
            discharge_w:        ontlaadvermogen (W)
            buy_price_eur_kwh:  prijs waartegen geladen is (voor spread-check)
            min_spread:         minimale netto marge voor eigenverbruik-scenario

        Returns:
            (bool, reden, effectieve_waarde_eur_kwh)
        """
        discharge_w   = max(1.0, discharge_w)
        house_fraction = min(1.0, house_load_w / discharge_w)
        eff_value = self.discharge_value_eur_kwh(sell_price_eur_kwh, house_fraction)

        net = eff_value - buy_price_eur_kwh - self.cycle_cost_eur_kwh

        if net >= min_spread:
            return True, (
                f"Ontladen rendabel: waarde €{eff_value:.4f}/kWh "
                f"(huis {house_fraction:.0%} eigen, {1-house_fraction:.0%} export @ "
                f"{self.saldering_pct:.0%} saldering), netto €{net:.4f}/kWh"
            ), eff_value

        # Niet winstgevend — geef aan waarom
        if house_fraction > 0.5 and self.saldering_pct < 0.5:
            reason = (
                f"Export niet rendabel bij {self.saldering_pct:.0%} saldering "
                f"(netto €{net:.4f}/kWh < drempel €{min_spread:.4f}); "
                f"huis dekt slechts {house_fraction:.0%} van ontladen"
            )
        else:
            reason = (
                f"Ontladen niet rendabel: waarde €{eff_value:.4f}/kWh, "
                f"netto €{net:.4f}/kWh < drempel €{min_spread:.4f}"
            )
        return False, reason, eff_value

    # ── Informatief ───────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Gestructureerde samenvatting voor HA-sensor of dashboard."""
        return {
            "year":               self.year,
            "saldering_pct":      round(self.saldering_pct * 100, 0),
            "fully_active":       self.saldering_pct >= 1.0,
            "fully_abolished":    self.saldering_pct == 0.0,
            "cycle_cost_eur_kwh": self.cycle_cost_eur_kwh,
            "roundtrip_eff":      BATTERY_ROUNDTRIP_EFFICIENCY,
            "min_spread_eur_kwh": MIN_ARBITRAGE_SPREAD_EUR,
        }

    def __repr__(self) -> str:
        return (
            f"SalderingContext(jaar={self.year}, "
            f"saldering={self.saldering_pct:.0%}, "
            f"cycluskosten=€{self.cycle_cost_eur_kwh:.3f}/kWh)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# v1.32: SalderingCalibrator — leert het effectieve salderingpercentage
#         vanuit gemeten import/export in plaats van de wettelijke waarde.
#
# Sommige energiemaatschappijen rekenen 2026 anders af dan de wet zegt,
# of hanteren een andere aanrekenmethode (per dag, per maand, per jaar).
# CloudEMS meet elke dag de werkelijke verhoudingen en past de
# SalderingContext aan als de afwijking structureel is.
# ══════════════════════════════════════════════════════════════════════════════

import logging as _log_sal
_LOGGER_CAL = _log_sal.getLogger(__name__ + ".calibrator")

# Minimale dagelijkse export om een meting zinvol te achten
MIN_EXPORT_KWH_FOR_SAMPLE = 0.5
# Aantal dagsamples om een betrouwbare kalibratie te maken
MIN_SAMPLES_FOR_CALIBRATION = 14
# Maximale afwijking van de wettelijke waarde die we accepteren
MAX_CALIBRATION_DEVIATION = 0.20   # ±20% van de wettelijke waarde
# EMA alpha voor dagsample leren
CAL_ALPHA = 0.10


class SalderingCalibrator:
    """
    Leert het effectief salderingspercentage vanuit dagelijkse metingen.

    Gebruik:
        cal = SalderingCalibrator(hass, store)
        await cal.async_setup()
        cal.record_day(import_kwh=8.5, export_kwh=4.2, verrekend_kwh=1.5)
        pct = cal.get_effective_pct(legal_pct=0.36)
        ctx = SalderingContext.for_current_year()
        ctx.saldering_pct = pct  # ← overschrijf wettelijke waarde met geleerde

    Wat het meet:
        Effectief % = verrekend_kWh / export_kWh
        Als verrekend_kWh niet beschikbaar is, gebruik dan import/export ratio
        als proxy (benadert het salderingpercentage bij bekende baseline).
    """

    STORE_KEY     = "cloudems_saldering_calibrator_v1"
    STORE_VERSION = 1

    def __init__(self, hass=None, store=None) -> None:
        self._hass  = hass
        self._store = store
        self._samples: list[dict] = []   # [{date, import_kwh, export_kwh, verrekend_kwh}]
        self._ema_pct: float | None = None   # geleerd effectief percentage
        self._loaded = False

    async def async_setup(self) -> None:
        if not self._store:
            if self._hass:
                from homeassistant.helpers.storage import Store as _St
                self._store = _St(self._hass, self.STORE_VERSION, self.STORE_KEY)
            else:
                return
        try:
            raw = await self._store.async_load() or {}
            self._samples  = raw.get("samples", [])[-365:]
            self._ema_pct  = raw.get("ema_pct")
            _LOGGER_CAL.debug(
                "SalderingCalibrator: %d dagsamples geladen, ema_pct=%s",
                len(self._samples), f"{self._ema_pct:.3f}" if self._ema_pct else "–",
            )
        except Exception as exc:
            _LOGGER_CAL.warning("SalderingCalibrator: laden mislukt: %s", exc)
        self._loaded = True

    async def async_save(self) -> None:
        if not self._store:
            return
        try:
            await self._store.async_save({
                "samples": self._samples[-365:],
                "ema_pct": self._ema_pct,
            })
        except Exception as exc:
            _LOGGER_CAL.warning("SalderingCalibrator: opslaan mislukt: %s", exc)

    def record_day(
        self,
        date_str: str,
        import_kwh: float,
        export_kwh: float,
        verrekend_kwh: float | None = None,
    ) -> None:
        """
        Registreer dagelijkse import/export meting.

        verrekend_kwh: kWh die direct verrekend werd (optioneel).
          Als niet beschikbaar: schatten we het via import/export ratio.
        """
        if export_kwh < MIN_EXPORT_KWH_FOR_SAMPLE:
            return
        # Dedupliceer op datum
        self._samples = [s for s in self._samples if s["date"] != date_str]

        measured_pct: float
        if verrekend_kwh is not None and verrekend_kwh >= 0:
            measured_pct = min(1.0, verrekend_kwh / max(0.01, export_kwh))
        else:
            # Proxy: het deel van de export dat overeenkomt met verlaagde import
            # Aanname: zonder saldering was import = import + export (alles van net)
            # Met saldering = import_kwh (netto). Dus verrekend ≈ export × (1 - import/totaal)
            total = import_kwh + export_kwh
            if total < 0.1:
                return
            measured_pct = min(1.0, max(0.0, export_kwh / total))

        self._samples.append({
            "date":       date_str,
            "import_kwh": round(import_kwh, 3),
            "export_kwh": round(export_kwh, 3),
            "pct":        round(measured_pct, 4),
        })

        # EMA update
        if self._ema_pct is None:
            self._ema_pct = measured_pct
        else:
            self._ema_pct = CAL_ALPHA * measured_pct + (1.0 - CAL_ALPHA) * self._ema_pct

        _LOGGER_CAL.debug(
            "SalderingCalibrator: dag %s export=%.2f kWh, gemeten pct=%.1f%%, ema=%.1f%%",
            date_str, export_kwh, measured_pct * 100, self._ema_pct * 100,
        )

    def get_effective_pct(self, legal_pct: float) -> float:
        """
        Geef het te gebruiken salderingspercentage terug.

        Als er genoeg data is EN de geleerde waarde valt binnen de
        toegestane afwijkingsband → gebruik de geleerde waarde.
        Anders → gebruik de wettelijke waarde.
        """
        if self._ema_pct is None or len(self._samples) < MIN_SAMPLES_FOR_CALIBRATION:
            return legal_pct

        lo = legal_pct * (1.0 - MAX_CALIBRATION_DEVIATION)
        hi = legal_pct * (1.0 + MAX_CALIBRATION_DEVIATION)
        calibrated = max(lo, min(hi, self._ema_pct))

        if abs(calibrated - legal_pct) > 0.02:
            _LOGGER_CAL.info(
                "SalderingCalibrator: wettelijk %.0f%% → gecalibreerd %.1f%% "
                "(%d dagsamples)",
                legal_pct * 100, calibrated * 100, len(self._samples),
            )
        return round(calibrated, 4)

    def get_calibrated_context(self) -> "SalderingContext":
        """
        Geef een SalderingContext terug met het gecalibreerde percentage.
        Handig als drop-in vervanging van SalderingContext.for_current_year().
        """
        ctx = SalderingContext.for_current_year()
        ctx.saldering_pct = self.get_effective_pct(ctx.saldering_pct)
        return ctx

    def get_diagnostics(self) -> dict:
        return {
            "samples":     len(self._samples),
            "ema_pct":     round(self._ema_pct * 100, 1) if self._ema_pct else None,
            "ready":       len(self._samples) >= MIN_SAMPLES_FOR_CALIBRATION,
            "recent_days": [s["date"] for s in self._samples[-7:]],
        }
