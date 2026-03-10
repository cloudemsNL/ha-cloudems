# -*- coding: utf-8 -*-
"""CloudEMS — ERE Certificaten Module (v2.6).

Emissiereductie-eenheden (ERE's) — RED3/Nederlandse implementatie 2026.

WAT ZIJN ERE's
══════════════
Een ERE = 1 kg CO₂-equivalent ketenemissiereductie t.o.v. fossiele referentie.
Brandstofleveranciers zijn verplicht ERE's in te kopen bij elektrische rijders.
Inboekdienstverleners (Laadloon, FincoEnergies, Voltico, Den Hartog) kopen
de kWh-data van jouw MID-laadpaal en verkopen ERE's namens jou.

VEREISTEN
═════════
  - MID-gecertificeerde laadpaal (meter IN de laadpaal, niet in meterkast)
  - Laadpaal met HA-integratie (OCPP, Zaptec, Alfen, Easee, Smappee...)
  - OF: aparte EAN-aansluiting voor laadpaal
  - Registratie bij inboekdienstverlener (eenmalig, voor mei 2026)

BEREKENING (officieel NEa / RED3)
══════════════════════════════════
  ERE = kWh × aandeel_hernieuwbaar × 183 g/MJ × 3.6 MJ/kWh ÷ 1000

  Waarbij aandeel_hernieuwbaar:
  - Groenstroomcontract: 100% (bewijs via leveringsgaranties)
  - Standaard NL stroomnet: ~50% (landelijk gemiddelde 2026)
  - Eigen zonnepanelen: berekend op basis van solar-overschot t.t.v. laden

  Opbrengst:
  - ERE marktprijs begin 2026: ~€0.40/ERE (fluctueert)
  - Na aftrek inboekfee (~20%): netto ~€0.03-€0.10/geladen kWh
  - Typisch particulier (4.000 kWh/jaar): €120-€400/jaar

OPTIMALISATIE
═════════════
CloudEMS verhoogt ERE-waarde door:
  1. Laden op solar-piek → aandeel hernieuwbaar = 100% → meer ERE's
  2. Laden op goedkope/groene uren → dubbel voordeel (lage kWh-prijs + ERE)
  3. Tijdsvakken bijhouden: welk % van lading was aantoonbaar groen?

RAPPORTAGE
══════════
  - Kwartaalrapport als PDF-ready dict (voor inboekdienstverlener)
  - Jaaroverzicht met maandelijkse breakdown
  - Exporteer als CSV/JSON voor eigen administratie

MID-LAADPAAL SENSOR
════════════════════
Ondersteunde HA-integraties met MID-meter:
  - Zaptec: sensor.*_energy (kWh)
  - Alfen:  sensor.*_meter_value (kWh)
  - OCPP:   sensor.*_energy_active_import_register
  - Smappee: sensor.*_session_kwh
  - Easee:  sensor.*_lifetime_energy (geen MID!)
  - Ohme:   sensor.*_charge_session_kwh

Copyright 2025 CloudEMS
"""
from __future__ import annotations

import csv
import io
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ── ERE Rekenmodel (NEa RED3) ─────────────────────────────────────────────────

# Officiële omrekeningsfactor: 183 g/MJ × 3.6 MJ/kWh ÷ 1000 g/kg = 0.6588 kg CO₂/kWh
ERE_KG_PER_KWH_FACTOR = 183 * 3.6 / 1000   # = 0.6588

# Standaard NL stroomnet hernieuwbaar aandeel 2026 (ca. 50%)
NL_GRID_RENEWABLE_PCT_DEFAULT = 0.50

# Minimale hernieuwbaarheid voor groenstroomcontract claim
GREEN_CONTRACT_RENEWABLE_PCT = 1.00

# Geschatte marktprijs ERE (€/kg CO₂) — begin 2026, fluctueert
ERE_MARKET_PRICE_EUR = 0.40   # €0.40/ERE (≈ 0.40/kg CO₂)

# Typische inboekfee percentage
ERE_INBOEKFEE_PCT = 0.20   # 20%


def bereken_ere(kwh: float, renewable_pct: float) -> float:
    """Bereken aantal ERE's voor een hoeveelheid geladen kWh.

    ERE = kWh × renewable_pct × 183 g/MJ × 3.6 MJ/kWh ÷ 1000
    """
    return kwh * renewable_pct * ERE_KG_PER_KWH_FACTOR


def ere_opbrengst_eur(ere: float, fee_pct: float = ERE_INBOEKFEE_PCT) -> float:
    """Netto opbrengst in EUR na aftrek inboekfee."""
    return ere * ERE_MARKET_PRICE_EUR * (1 - fee_pct)


# ── Laadsessie record ─────────────────────────────────────────────────────────

@dataclass
class LaadSessie:
    """Eén geregistreerde laadsessie voor ERE-rapportage."""
    ts_start:       float   # Unix timestamp
    ts_eind:        float
    kwh:            float
    renewable_pct:  float   # 0.0–1.0
    voertuig:       str     # "auto" | "ebike" | "scooter"
    laadpaal_id:    str
    is_solar:       bool    = False
    mid_meting:     bool    = True   # via MID-gecertificeerde meter

    @property
    def ere(self) -> float:
        return bereken_ere(self.kwh, self.renewable_pct)

    @property
    def opbrengst_eur(self) -> float:
        return ere_opbrengst_eur(self.ere)

    @property
    def datum(self) -> str:
        return datetime.fromtimestamp(self.ts_start, tz=timezone.utc).strftime("%Y-%m-%d")

    @property
    def kwartaal(self) -> str:
        dt = datetime.fromtimestamp(self.ts_start, tz=timezone.utc)
        q  = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"

    @property
    def maand(self) -> str:
        return datetime.fromtimestamp(self.ts_start, tz=timezone.utc).strftime("%Y-%m")

    def to_dict(self) -> dict:
        return {
            "datum":          self.datum,
            "start":          datetime.fromtimestamp(self.ts_start, tz=timezone.utc).isoformat(),
            "eind":           datetime.fromtimestamp(self.ts_eind,  tz=timezone.utc).isoformat(),
            "kwh":            round(self.kwh, 3),
            "renewable_pct":  round(self.renewable_pct * 100, 1),
            "ere":            round(self.ere, 3),
            "opbrengst_eur":  round(self.opbrengst_eur, 2),
            "voertuig":       self.voertuig,
            "laadpaal_id":    self.laadpaal_id,
            "is_solar":       self.is_solar,
            "mid_meting":     self.mid_meting,
        }


# ── ERE Module ────────────────────────────────────────────────────────────────

class EREManager:
    """Hoofdklasse voor ERE-certificaten registratie, optimalisatie en rapportage.

    Gebruik vanuit coordinator:
        ere = EREManager(hass, config)
        await ere.async_setup()
        await ere.async_update(coordinator_data)
        rapport = ere.generate_kwartaal_rapport("2026-Q1")
    """

    STORAGE_KEY = "cloudems_ere_v1"
    MAX_SESSIES = 10_000   # bewaar max 10k sessies

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._store  = None
        self._sessies: list[LaadSessie] = []

        # Actieve laadsessie tracking
        self._active: dict[str, dict] = {}   # laadpaal_id → {start_ts, start_kwh, ...}

        # Groenstroom configuratie
        self._heeft_groencontract = bool(config.get("ere_green_contract", False))
        self._renewable_override  = config.get("ere_renewable_pct")   # 0.0–1.0 of None

        # MID-laadpaal entities (één of meerdere)
        # Config: ere_charger_entities: ["sensor.zaptec_energy", ...]
        self._charger_entities: list[str] = config.get("ere_charger_entities", [])
        self._charger_type: str           = config.get("ere_charger_type", "generic")

        # Snapshot van laatste kWh-stand per sensor (voor delta-berekening)
        self._kwh_snapshot: dict[str, float] = {}

        # Optimalisatie: laadadvies
        self._current_advice: dict = {}

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, 1, self.STORAGE_KEY)
        saved = await self._store.async_load() or {}

        for sd in saved.get("sessies", []):
            try:
                self._sessies.append(LaadSessie(**sd))
            except (TypeError, KeyError):
                pass

        self._kwh_snapshot = saved.get("kwh_snapshot", {})
        _LOGGER.info("ERE module geladen: %d sessies, %.1f kWh totaal, %.1f ERE totaal",
                     len(self._sessies),
                     sum(s.kwh for s in self._sessies),
                     sum(s.ere for s in self._sessies))

    async def async_update(self, data: dict) -> dict:
        """Verwerk coordinator data — detecteer laadsessies en update ERE-teller."""
        solar_surplus_w = float(data.get("solar_surplus_w") or 0)
        solar_pv_w      = float(data.get("solar_power_w") or 0)
        price_eur_kwh   = float((data.get("energy_price") or {}).get("current_eur_kwh") or 0)
        price_forecast  = (data.get("energy_price") or {}).get("forecast", [])
        grid_w          = float(data.get("grid_power_w") or 0)

        # Bereken realtime hernieuwbaarheid op basis van solar vs grid
        renewable_pct_now = self._calc_renewable_pct(solar_pv_w, grid_w)

        # Poll MID-meter sensors voor kWh-delta
        for eid in self._charger_entities:
            await self._poll_charger(eid, renewable_pct_now, solar_surplus_w, data)

        # Genereer laadadvies
        self._current_advice = self._calc_charge_advice(
            solar_surplus_w, price_eur_kwh, price_forecast, renewable_pct_now
        )

        # Periodiek opslaan
        await self._maybe_save()

        return self.get_status()

    def _calc_renewable_pct(self, solar_w: float, grid_w: float) -> float:
        """Berekent realtime % hernieuwbaar van huidig verbruik."""
        if self._heeft_groencontract:
            return GREEN_CONTRACT_RENEWABLE_PCT
        if self._renewable_override is not None:
            return float(self._renewable_override)

        # Als we weten hoeveel solar er is: berekening op basis van mix
        total_load_w = solar_w + max(0, grid_w)
        if total_load_w > 0 and solar_w > 0:
            solar_fraction = min(1.0, solar_w / total_load_w)
            # Grid-aandeel × NL gemiddeld hernieuwbaar + solar-aandeel × 100%
            return solar_fraction + (1 - solar_fraction) * NL_GRID_RENEWABLE_PCT_DEFAULT

        return NL_GRID_RENEWABLE_PCT_DEFAULT

    async def _poll_charger(
        self, eid: str, renewable_pct: float, solar_surplus_w: float, data: dict
    ) -> None:
        """Lees kWh-stand van MID-sensor en detecteer sessie-start/eind."""
        st = self._hass.states.get(eid)
        if not st or st.state in ("unavailable", "unknown"):
            return

        try:
            kwh_now = float(st.state)
        except (ValueError, TypeError):
            return

        kwh_prev = self._kwh_snapshot.get(eid)
        self._kwh_snapshot[eid] = kwh_now

        if kwh_prev is None:
            return

        delta_kwh = kwh_now - kwh_prev

        # Sessie-einde detectie: delta stopt (< 0.005 kWh/cyclus)
        if eid in self._active:
            active = self._active[eid]
            if delta_kwh < 0.005:
                # Sessie voorbij
                sessie_kwh = kwh_now - active["start_kwh"]
                if sessie_kwh >= 0.01:
                    is_solar = active.get("solar_during", False)
                    avg_renew = active.get("renewable_sum", 0) / max(1, active.get("ticks", 1))
                    sessie = LaadSessie(
                        ts_start=active["start_ts"],
                        ts_eind=self._now_ts(),
                        kwh=round(sessie_kwh, 3),
                        renewable_pct=min(1.0, max(0.0, avg_renew)),
                        voertuig=active.get("voertuig", "auto"),
                        laadpaal_id=eid,
                        is_solar=is_solar,
                        mid_meting=True,
                    )
                    self._sessies.append(sessie)
                    if len(self._sessies) > self.MAX_SESSIES:
                        self._sessies = self._sessies[-self.MAX_SESSIES:]
                    _LOGGER.info(
                        "ERE: sessie afgesloten — %.3f kWh, %.0f%% hernieuwbaar, "
                        "%.3f ERE, €%.2f netto",
                        sessie.kwh, sessie.renewable_pct * 100,
                        sessie.ere, sessie.opbrengst_eur
                    )
                del self._active[eid]
            else:
                # Sessie loopt door
                active["renewable_sum"] += renewable_pct
                active["ticks"] += 1
                if solar_surplus_w > 50:
                    active["solar_during"] = True

        elif delta_kwh >= 0.005:
            # Sessie-start
            self._active[eid] = {
                "start_ts":       self._now_ts(),
                "start_kwh":      kwh_prev,
                "renewable_sum":  renewable_pct,
                "ticks":          1,
                "solar_during":   solar_surplus_w > 50,
                "voertuig":       self._detect_vehicle(data),
            }
            _LOGGER.info("ERE: laadsessie gestart via %s", eid)

    def _detect_vehicle(self, data: dict) -> str:
        """Schat voertuigtype op basis van andere actieve sensoren."""
        # E-bike actief?
        ebike_data = data.get("bosch_ebike", {})
        for fiets in ebike_data.get("fietsen", []):
            if fiets.get("is_charging"):
                return "ebike"
        # Micro-mobility?
        micro = data.get("micro_mobility", {})
        for sess in (micro.get("active_sessions") or []):
            vtype = sess.get("vehicle_type", "")
            if vtype in ("ebike", "scooter"):
                return vtype
        return "auto"

    def _calc_charge_advice(
        self,
        solar_w: float,
        price_eur: float,
        forecast: list,
        renewable_pct: float,
    ) -> dict:
        """Geeft laadadvies terug dat ERE én kosten optimaliseert."""
        cheap_threshold = float(self._config.get("ev_cheap_price_threshold", 0.18))

        # Solar: hoog hernieuwbaar + gratis stroom
        if solar_w > 500:
            ere_per_kwh = bereken_ere(1.0, 1.0)   # 100% solar
            netto       = ere_opbrengst_eur(ere_per_kwh)
            return {
                "advies":          "solar",
                "reden":           f"Solar-overschot {solar_w:.0f}W — 100% hernieuwbaar",
                "renewable_pct":   1.0,
                "ere_per_kwh":     round(ere_per_kwh, 4),
                "netto_per_kwh":   round(netto + price_eur * 0, 4),   # gratis stroom
                "urgentie":        "hoog",
            }

        # Goedkoop tarief
        if price_eur <= cheap_threshold:
            ere_per_kwh = bereken_ere(1.0, renewable_pct)
            netto       = ere_opbrengst_eur(ere_per_kwh)
            return {
                "advies":        "nu_laden",
                "reden":         f"Goedkoop tarief {price_eur:.3f} EUR/kWh + {renewable_pct*100:.0f}% hernieuwbaar",
                "renewable_pct": renewable_pct,
                "ere_per_kwh":   round(ere_per_kwh, 4),
                "netto_per_kwh": round(netto - price_eur, 4),
                "urgentie":      "normaal",
            }

        # Zoek beste uur in forecast (combineer lage prijs + geschatte solar)
        beste = None
        beste_score = -999
        for slot in forecast[:24]:
            try:
                slot_price = float(slot.get("price", 999))
                slot_hour  = int(slot.get("hour", 12))
                # Solar-uren: 9-16 = hoger hernieuwbaar aandeel
                solar_bonus = 0.3 if 9 <= slot_hour <= 16 else 0.0
                ren         = min(1.0, renewable_pct + solar_bonus)
                ere_val     = bereken_ere(1.0, ren)
                netto_val   = ere_opbrengst_eur(ere_val) - slot_price
                if netto_val > beste_score:
                    beste_score = netto_val
                    beste       = {"uur": slot_hour, "prijs": slot_price, "renewable": ren, "netto": netto_val}
            except (ValueError, TypeError, KeyError):
                pass

        if beste:
            return {
                "advies":        "wachten",
                "reden":         f"Beste uur: {beste['uur']}:00 — {beste['prijs']:.3f} EUR/kWh, netto {beste['netto']:.4f} EUR/kWh na ERE",
                "beste_uur":     beste["uur"],
                "renewable_pct": beste["renewable"],
                "ere_per_kwh":   round(bereken_ere(1.0, beste["renewable"]), 4),
                "netto_per_kwh": round(beste["netto"], 4),
                "urgentie":      "laag",
            }

        return {
            "advies":        "onbekend",
            "reden":         "Geen forecast beschikbaar",
            "renewable_pct": renewable_pct,
            "urgentie":      "laag",
        }

    # ── Statistieken ─────────────────────────────────────────────────────────

    def _stats_for(self, sessies: list[LaadSessie]) -> dict:
        if not sessies:
            return {"kwh": 0, "ere": 0, "opbrengst_eur": 0, "sessies": 0,
                    "avg_renewable_pct": 0, "solar_sessies": 0}
        kwh   = sum(s.kwh for s in sessies)
        ere   = sum(s.ere for s in sessies)
        obrst = sum(s.opbrengst_eur for s in sessies)
        renew = sum(s.renewable_pct for s in sessies) / len(sessies)
        solar = sum(1 for s in sessies if s.is_solar)
        return {
            "kwh":               round(kwh, 2),
            "ere":               round(ere, 2),
            "opbrengst_eur":     round(obrst, 2),
            "sessies":           len(sessies),
            "avg_renewable_pct": round(renew * 100, 1),
            "solar_sessies":     solar,
        }

    def get_status(self) -> dict:
        now  = datetime.now(timezone.utc)
        jaar = str(now.year)
        mnd  = now.strftime("%Y-%m")
        kw   = f"{now.year}-Q{(now.month-1)//3+1}"

        sessies_jaar   = [s for s in self._sessies if s.datum.startswith(jaar)]
        sessies_maand  = [s for s in self._sessies if s.maand == mnd]
        sessies_kw     = [s for s in self._sessies if s.kwartaal == kw]

        # Jaarprojektie op basis van YTD
        days_elapsed = max(1, (now - datetime(now.year, 1, 1, tzinfo=timezone.utc)).days)
        kwh_ytd      = sum(s.kwh for s in sessies_jaar)
        ere_ytd      = sum(s.ere for s in sessies_jaar)
        kwh_proj     = kwh_ytd / days_elapsed * 365
        ere_proj     = ere_ytd / days_elapsed * 365
        obrst_proj   = ere_opbrengst_eur(ere_proj)

        return {
            "jaar":           self._stats_for(sessies_jaar),
            "maand":          self._stats_for(sessies_maand),
            "kwartaal":       self._stats_for(sessies_kw),
            "totaal":         self._stats_for(self._sessies),
            "projectie_jaar": {
                "kwh":           round(kwh_proj, 0),
                "ere":           round(ere_proj, 0),
                "opbrengst_eur": round(obrst_proj, 0),
            },
            "laad_advies":    self._current_advice,
            "ere_prijs_eur":  ERE_MARKET_PRICE_EUR,
            "inboekfee_pct":  ERE_INBOEKFEE_PCT * 100,
            "heeft_mid_meter": bool(self._charger_entities),
            "heeft_groencontract": self._heeft_groencontract,
            "actieve_sessies": len(self._active),
        }

    # ── Rapportage ────────────────────────────────────────────────────────────

    def generate_kwartaal_rapport(self, kwartaal: Optional[str] = None) -> dict:
        """Genereer kwartaalrapport voor inboekdienstverlener.

        kwartaal: "2026-Q1" of None voor huidig kwartaal.
        """
        if kwartaal is None:
            now = datetime.now(timezone.utc)
            kwartaal = f"{now.year}-Q{(now.month-1)//3+1}"

        sessies = [s for s in self._sessies if s.kwartaal == kwartaal]
        if not sessies:
            return {"kwartaal": kwartaal, "sessies": 0, "error": "Geen data"}

        # Per voertuigtype opsplitsen
        per_type: dict[str, list] = defaultdict(list)
        for s in sessies:
            per_type[s.voertuig].append(s)

        rapport = {
            "kwartaal":         kwartaal,
            "gegenereerd_op":   datetime.now(timezone.utc).isoformat(),
            "samenvatting":     self._stats_for(sessies),
            "per_voertuig":     {
                vtype: self._stats_for(ss) for vtype, ss in per_type.items()
            },
            "per_laadpaal":     {
                eid: self._stats_for([s for s in sessies if s.laadpaal_id == eid])
                for eid in {s.laadpaal_id for s in sessies}
            },
            "maand_breakdown":  {},
            "sessie_detail":    [s.to_dict() for s in sorted(sessies, key=lambda x: x.ts_start)],
            "rekenregel":       f"ERE = kWh × hernieuwbaar% × {ERE_KG_PER_KWH_FACTOR:.4f} kg/kWh",
            "marktprijs":       f"€{ERE_MARKET_PRICE_EUR}/ERE (schatting, fluctueert)",
            "inboekfee":        f"{ERE_INBOEKFEE_PCT*100:.0f}%",
        }

        # Maand-breakdown
        mnd_groups: dict[str, list] = defaultdict(list)
        for s in sessies:
            mnd_groups[s.maand].append(s)
        rapport["maand_breakdown"] = {
            mnd: self._stats_for(ss) for mnd, ss in sorted(mnd_groups.items())
        }

        return rapport

    def export_csv(self, kwartaal: Optional[str] = None) -> str:
        """Exporteer laadsessies als CSV-string voor inboekdienstverlener."""
        now = datetime.now(timezone.utc)
        kw  = kwartaal or f"{now.year}-Q{(now.month-1)//3+1}"
        sessies = [s for s in self._sessies if s.kwartaal == kw]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "datum", "start", "eind", "kwh", "renewable_pct",
            "ere", "opbrengst_eur", "voertuig", "laadpaal_id",
            "is_solar", "mid_meting"
        ])
        writer.writeheader()
        for s in sorted(sessies, key=lambda x: x.ts_start):
            writer.writerow(s.to_dict())
        return output.getvalue()

    def export_json(self, kwartaal: Optional[str] = None) -> str:
        """Exporteer kwartaalrapport als JSON-string."""
        rapport = self.generate_kwartaal_rapport(kwartaal)
        return json.dumps(rapport, indent=2, ensure_ascii=False)

    def _now_ts(self) -> float:
        return datetime.now(timezone.utc).timestamp()

    _save_counter = 0

    async def _maybe_save(self) -> None:
        self._save_counter += 1
        if self._save_counter % 60 != 0:   # elke ~10 minuten
            return
        if self._store:
            try:
                await self._store.async_save({
                    "sessies":      [s.__dict__ for s in self._sessies[-1000:]],
                    "kwh_snapshot": self._kwh_snapshot,
                })
            except Exception:
                pass
