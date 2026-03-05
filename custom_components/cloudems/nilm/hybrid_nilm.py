"""
CloudEMS Hybride NILM — v1.2.0

Verbetert de NILM-nauwkeurigheid via drie aanvullende lagen bovenop de bestaande
NILMDetector, zonder bestaande functionaliteit te breken:

LAAG 1 — Smart Plug Ankering (automatisch)
  Auto-discovery vindt vermogenssensoren in HA (Shelly, Tasmota, ESPHome…).
  Herkende sensoren (wasmachine, droger, warmtepomp…) worden ankers:
    • Hun vermogen wordt direct als 100%-zekere detectie ingevoerd
    • Hun vermogen wordt afgetrokken van het restsignaal → schoner NILM-signaal
    → Nauwkeurigheid stijgt van ~65% naar ~85%+ voor geankerde apparaten

  v1.1.0: Ook generieke stopcontacten (device_type="socket") worden ontdekt,
    zodat ALLE smart plugs — ook zonder herkenbare apparaatnaam — zichtbaar zijn.

LAAG 2 — Context-bewuste Bayesiaanse priors
  Classificatiescores worden bijgesteld op basis van:
    • Buitentemperatuur  → warmtepomp/boiler boost bij kou, AC boost bij hitte
    • Tijdstip + weekdag → apparaten die op dit moment zelden draaien: penalty
    • Seizoen            → zomer vs. winter device-verdeling
    • Vermogensbereik    → kleine delta → grote apparaten minder waarschijnlijk
  Priors veranderen de eindconfidentie maar vervangen de detector NIET.

LAAG 3 — 3-fase Balansanalyse + DSMR5 Fase-correlatie
  Bij 3-fase installaties detecteert de balans-analyzer of een event
  afkomstig is van een 1-fase of 3-fase apparaat:
    • Gelijktijdige ~gelijke delta op alle 3 fasen → 3-fase (WP, EV)
    • Delta slechts op 1 fase → 1-fase (wasmachine, droger)

  v1.1.0 Fase-correlatie stopcontacten via DSMR5:
    • Elke keer dat het vermogen van een stopcontact significant wijzigt
      (>SOCKET_PHASE_MIN_DELTA_W), wordt de delta vergeleken met de actuele
      per-fase deltas van de DSMR5-meter (L1, L2, L3).
    • De fase waarvan de delta het best overeenkomt (laagste relatieve afwijking)
      krijgt toegewezen aan het stopcontact.
    • Zodra een fase bevestigd is (SOCKET_PHASE_CONFIRM_COUNT keer correct),
      wordt hij als definitief gemarkeerd en niet meer opnieuw bepaald.

Integratie:
  HybridNILM.async_tick() elke updatecyclus via coordinator
  HybridNILM.enrich_matches() in NILMDetector._async_process_event()

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .smart_sensor_discovery import SmartSensorDiscovery, DiscoveryResult

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────
SMART_PLUG_STALE_S        = 120
PRIOR_MAX_BOOST           = 1.40
PRIOR_MAX_PENALTY         = 0.50
TEMP_COLD                 =  8.0
TEMP_HOT                  = 24.0
PHASE_WIN_S               =  3.0
PHASE_MIN_DELTA_W         = 200.0
PHASE_RATIO_MIN           = 0.26
PHASE_RATIO_MAX           = 0.40
THREE_PHASE_TYPES         = {"ev_charger", "heat_pump", "boiler", "dryer"}

# ── v1.1.0: Stopcontact fase-correlatie via DSMR5 ─────────────────────────────
# Minimale vermogenswijziging (W) voordat fase-correlatie wordt uitgevoerd
SOCKET_PHASE_MIN_DELTA_W  = 30.0
# Tijdvenster (s) waarbinnen DSMR5 fase-snapshot geldig is voor correlatie
SOCKET_PHASE_WIN_S        = 6.0
# Maximale relatieve afwijking (0.0–1.0) voor een goede fase-match
SOCKET_PHASE_MAX_REL_ERR  = 0.35
# Aantal opeenvolgende correcte matches vóór fase als definitief geldt
SOCKET_PHASE_CONFIRM_COUNT = 3
# Hervalidatie-interval: na hoeveel seconden wordt een bevestigde fase opnieuw
# gecontroleerd? Standaard 24 uur. Zo worden verplaatste stopcontacten automatisch
# opgepikt zonder dat de initiële bevestiging telkens opnieuw moet.
SOCKET_PHASE_RECHECK_S    = 86_400  # 24 uur


# ── Dataklassen ───────────────────────────────────────────────────────────────

@dataclass
class AnchoredDevice:
    plug_id:     str
    entity_id:   str
    device_type: str
    name:        str
    phase:       str = "L1"
    power_w:     float = 0.0
    is_on:       bool  = False
    last_update: float = field(default_factory=time.time)

    # v1.1.0: DSMR5 fase-correlatie tracking
    prev_power_w:         float = 0.0          # vermogen bij vorige tick
    phase_confirmed:      bool  = False         # fase bevestigd via DSMR5
    phase_confirmed_at:   float = 0.0          # timestamp van laatste bevestiging
    phase_confirm_count:  int   = 0             # opeenvolgende correcte matches
    phase_last_candidate: str   = ""            # kandidaat-fase bij laatste event

    # v1.17.3: on_events counter zodat het apparaat ook in de NILM-kaart
    # verschijnt als het momenteel in stand-by is (on_events > 0 filter).
    on_events:   int   = 0                     # aantal keer dat het apparaat AAN was
    power_max_w: float = 0.0                   # hoogste gemeten vermogen (voor display)

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_update) > SMART_PLUG_STALE_S


@dataclass
class WeatherContext:
    temperature_c:  float = 15.0
    irradiance_wm2: float = 0.0
    humidity_pct:   float = 60.0
    timestamp:      float = field(default_factory=time.time)

    @property
    def is_cold(self) -> bool:  return self.temperature_c < TEMP_COLD
    @property
    def is_hot(self)  -> bool:  return self.temperature_c > TEMP_HOT
    @property
    def season(self) -> str:
        m = datetime.fromtimestamp(self.timestamp, tz=timezone.utc).month
        if m in (12, 1, 2): return "winter"
        if m in (3, 4, 5):  return "spring"
        if m in (6, 7, 8):  return "summer"
        return "autumn"


@dataclass
class PhaseSnapshot:
    phase:     str
    delta_w:   float
    timestamp: float = field(default_factory=time.time)


# ── HybridNILM ────────────────────────────────────────────────────────────────

class HybridNILM:
    """
    Hybride NILM-verrijkingslaag voor CloudEMS NILMDetector.

    Setup in coordinator.async_setup():
        self._hybrid = HybridNILM(hass)
        await self._hybrid.async_setup()

    Tick in coordinator._async_update_data():
        await self._hybrid.async_tick()

    Gebruik in NILMDetector._async_process_event() VOOR _handle_match():
        if self._hybrid:
            matches = self._hybrid.enrich_matches(
                matches, event.delta_power, event.phase, event.timestamp)
    """

    def __init__(self, hass, config: dict | None = None) -> None:
        self._hass      = hass
        self._config    = config or {}
        self._discovery = SmartSensorDiscovery(hass)
        self._anchors:  Dict[str, AnchoredDevice] = {}
        self._weather:  WeatherContext = WeatherContext()
        self._phase_snapshots: Dict[str, PhaseSnapshot] = {}
        self._stats = dict(enrich_calls=0, anchor_hits=0,
                           prior_boosts=0, prior_penalties=0,
                           phase_balance_hints=0, discoveries=0,
                           phase_correlations=0)
        self._last_diag_log: float = 0.0

    # ── Setup & tick ──────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        # Bouw exclusie-set vanuit CloudEMS config: grid, solar, battery,
        # P1, fase-sensoren — deze mogen NOOIT als NILM-anker worden geleerd.
        cfg = self._config
        excluded: set = set()

        # Directe sensoren
        for key in (
            "grid_sensor", "solar_sensor", "battery_sensor",
            "battery_soc_entity",
            "import_power_sensor", "export_power_sensor",
            "power_sensor_l1", "power_sensor_l2", "power_sensor_l3",
            "voltage_sensor_l1", "voltage_sensor_l2", "voltage_sensor_l3",
            "phase_sensors_L1", "phase_sensors_L2", "phase_sensors_L3",
        ):
            val = cfg.get(key, "")
            if val:
                excluded.add(val)

        # Omvormer entity_ids (lijst van dicts)
        for inv in cfg.get("inverter_configs", []):
            eid = inv.get("entity_id", "")
            if eid:
                excluded.add(eid)

        # Batterij power sensors (lijst van dicts)
        for bc in cfg.get("battery_configs", []):
            for bkey in ("power_sensor", "soc_sensor", "charge_sensor", "discharge_sensor"):
                beid = bc.get(bkey, "")
                if beid:
                    excluded.add(beid)

        if excluded:
            _LOGGER.info(
                "HybridNILM: %d CloudEMS-sensoren uitgesloten van NILM-leren: %s",
                len(excluded), ", ".join(sorted(excluded)),
            )

        self._discovery.set_excluded_entity_ids(excluded)
        await self._async_refresh()
        _LOGGER.info("CloudEMS HybridNILM klaar — %d ankers ontdekt", len(self._anchors))

    async def async_tick(self) -> None:
        await self._async_refresh()

    async def _async_refresh(self) -> None:
        try:
            result: DiscoveryResult = self._discovery.run()

            # Verwijder ankers voor sensoren die niet meer bestaan
            current_eids = {p.entity_id for p in result.plugs}
            for eid in [k for k in self._anchors if k not in current_eids]:
                del self._anchors[eid]

            # Registreer nieuwe ankers
            for plug in result.plugs:
                if plug.entity_id not in self._anchors:
                    self._anchors[plug.entity_id] = AnchoredDevice(
                        plug_id    = plug.entity_id,
                        entity_id  = plug.entity_id,
                        device_type= plug.device_type,
                        name       = plug.friendly_name,
                        phase      = plug.phase,
                    )
                    _LOGGER.info("HybridNILM: nieuw anker → %s (%s, %s)",
                                 plug.friendly_name, plug.device_type, plug.entity_id)
                    self._stats["discoveries"] += 1

            # Actuele vermogenswaardes inlezen
            for eid, anchor in self._anchors.items():
                pw = self._discovery.get_plug_power(eid)
                if pw is not None:
                    was_on = anchor.is_on
                    anchor.prev_power_w = anchor.power_w
                    anchor.power_w    = pw
                    anchor.is_on      = pw > 1.0   # v1.17.3: verlaagd van 5W → 1W
                    anchor.last_update = time.time()
                    # v1.17.3: bijhouden hoe vaak apparaat aan is geweest + max vermogen
                    if anchor.is_on and not was_on:
                        anchor.on_events += 1
                    if pw > anchor.power_max_w:
                        anchor.power_max_w = pw

            # v1.1.0: Fase bepalen via DSMR5 correlatie (voor alle stopcontacten)
            self._correlate_socket_phases()

            # Fase verfijnen via correlatie met NILM-snapshots (legacy fallback)
            self._refine_anchor_phases()

            # Weerdata
            self._refresh_weather()

            # Periodiek loggen
            if time.time() - self._last_diag_log > 600:
                active = sum(1 for a in self._anchors.values() if a.is_on and not a.is_stale)
                _LOGGER.debug("HybridNILM: %d ankers (%d actief), %.1f°C %s",
                              len(self._anchors), active,
                              self._weather.temperature_c, self._weather.season)
                self._last_diag_log = time.time()

        except Exception as exc:
            _LOGGER.debug("HybridNILM refresh fout: %s", exc)

    def _refine_anchor_phases(self) -> None:
        """Verfijn de fase van L1-standaard ankers via correlatie met fase-deltas."""
        for anchor in self._anchors.values():
            if anchor.phase != "L1" or not anchor.is_on or anchor.power_w < 100:
                continue
            best_ph, best_diff = None, float("inf")
            for ph, snap in self._phase_snapshots.items():
                if (time.time() - snap.timestamp) > 30:
                    continue
                diff = abs(abs(snap.delta_w) - anchor.power_w)
                if diff / max(anchor.power_w, 1.0) < 0.25 and diff < best_diff:
                    best_diff = diff
                    best_ph   = ph
            if best_ph and best_ph != anchor.phase:
                _LOGGER.debug("HybridNILM: %s fase verfijnd L1→%s", anchor.name, best_ph)
                anchor.phase = best_ph

    def _correlate_socket_phases(self) -> None:
        """
        v1.1.0 — Bepaal de fase van elk stopcontact via DSMR5 correlatie.

        Algoritme per stopcontact:
          1. Hervalidatie: als de fase al > SOCKET_PHASE_RECHECK_S geleden bevestigd
             is, wordt phase_confirmed gereset (de huidig toegewezen fase blijft
             behouden als startwaarde — bij gelijkblijvende situatie herbevestigt
             het systeem direct; bij een verplaatst stopcontact corrigeert het binnen
             3 schakelgebeurtenissen).
          2. Bereken de delta t.o.v. de vorige tick: delta = power_w − prev_power_w
          3. Als |delta| < SOCKET_PHASE_MIN_DELTA_W → geen informatie, skip
          4. Zoek in _phase_snapshots de fase waarvan de delta het best overeenkomt:
               relatieve_fout = |delta_snapshot − delta_socket| / max(|delta_socket|, 1)
          5. Als relatieve_fout ≤ SOCKET_PHASE_MAX_REL_ERR:
               - Kandidaat-fase gevonden
               - Als dit dezelfde fase is als de vorige kandidaat:
                   phase_confirm_count++
               - Anders:
                   phase_confirm_count = 1
                   phase_last_candidate = kandidaat
               - Als phase_confirm_count ≥ SOCKET_PHASE_CONFIRM_COUNT:
                   fase definitief vastgesteld (phase_confirmed = True,
                   phase_confirmed_at = now)
        """
        now = time.time()
        for anchor in self._anchors.values():

            # ── Stap 1: Dagelijkse hervalidatie ───────────────────────────────
            # Een bevestigde fase is nooit voor altijd zeker: het stopcontact kan
            # verplaatst zijn naar een andere groep. Elke SOCKET_PHASE_RECHECK_S
            # seconden zetten we de bevestiging terug naar "onbekend" zodat het
            # systeem opnieuw verifieert. De huidige fase-waarde blijft als
            # startwaarde staan; bij een onveranderde situatie herbevestigt het
            # binnen 3 deltagebeurtenissen. Bij een verplaatst stopcontact
            # corrigeert het automatisch.
            if anchor.phase_confirmed:
                age = now - anchor.phase_confirmed_at
                if age > SOCKET_PHASE_RECHECK_S:
                    _LOGGER.debug(
                        "HybridNILM: %s fase-hervalidatie na %.1fh (was: %s)",
                        anchor.name, age / 3600, anchor.phase,
                    )
                    anchor.phase_confirmed      = False
                    anchor.phase_confirm_count  = 0
                    anchor.phase_last_candidate = anchor.phase  # houd huidige fase als hint
                continue  # deze tick nog niet opnieuw correleren, wacht op delta

            # ── Stap 2: Delta berekenen ───────────────────────────────────────
            delta = anchor.power_w - anchor.prev_power_w
            if abs(delta) < SOCKET_PHASE_MIN_DELTA_W:
                continue

            # ── Stap 3: Beste fase-match zoeken ──────────────────────────────
            best_ph:     Optional[str] = None
            best_rel_err: float        = float("inf")

            for ph, snap in self._phase_snapshots.items():
                age = now - snap.timestamp
                if age > SOCKET_PHASE_WIN_S:
                    continue  # te oud
                rel_err = abs(snap.delta_w - delta) / max(abs(delta), 1.0)
                if rel_err < best_rel_err:
                    best_rel_err = rel_err
                    best_ph      = ph

            if best_ph is None or best_rel_err > SOCKET_PHASE_MAX_REL_ERR:
                # Geen goede match — reset kandidaat-streak
                anchor.phase_confirm_count  = 0
                anchor.phase_last_candidate = ""
                continue

            # ── Stap 4: Streaklogica ──────────────────────────────────────────
            if best_ph == anchor.phase_last_candidate:
                anchor.phase_confirm_count += 1
            else:
                anchor.phase_confirm_count  = 1
                anchor.phase_last_candidate = best_ph

            if anchor.phase_confirm_count >= SOCKET_PHASE_CONFIRM_COUNT:
                if anchor.phase != best_ph:
                    _LOGGER.info(
                        "HybridNILM: %s fase gewijzigd %s→%s via DSMR5 "
                        "(delta=%.0fW, fase-delta=%.0fW, err=%.0f%%)",
                        anchor.name, anchor.phase, best_ph, delta,
                        self._phase_snapshots[best_ph].delta_w,
                        best_rel_err * 100,
                    )
                else:
                    _LOGGER.info(
                        "HybridNILM: %s fase bevestigd als %s via DSMR5 "
                        "(delta=%.0fW, err=%.0f%%)",
                        anchor.name, best_ph, delta, best_rel_err * 100,
                    )
                anchor.phase              = best_ph
                anchor.phase_confirmed    = True
                anchor.phase_confirmed_at = now
                self._stats["phase_correlations"] += 1
            else:
                _LOGGER.debug(
                    "HybridNILM: %s fase-kandidaat %s (%d/%d) "
                    "(delta=%.0fW, rel_err=%.0f%%)",
                    anchor.name, best_ph,
                    anchor.phase_confirm_count, SOCKET_PHASE_CONFIRM_COUNT,
                    delta, best_rel_err * 100,
                )

    def _refresh_weather(self) -> None:
        temp = self._discovery.get_weather_value("temperature")
        irr  = self._discovery.get_weather_value("irradiance")
        hum  = self._discovery.get_weather_value("humidity")
        self._weather = WeatherContext(
            temperature_c  = temp if temp is not None else self._weather.temperature_c,
            irradiance_wm2 = irr  if irr  is not None else self._weather.irradiance_wm2,
            humidity_pct   = hum  if hum  is not None else self._weather.humidity_pct,
        )

    # ── Fase-tracking ─────────────────────────────────────────────────────────

    def record_phase_delta(self, phase: str, delta_w: float) -> None:
        self._phase_snapshots[phase] = PhaseSnapshot(phase=phase, delta_w=delta_w)

    # ── Kern-API ──────────────────────────────────────────────────────────────

    def enrich_matches(
        self,
        matches:   List[dict],
        delta_w:   float,
        phase:     str,
        timestamp: float,
    ) -> List[dict]:
        """
        Verrijkt matches met ankering, contextpriors en fase-balans.
        Aanroepen vóór _handle_match() in NILMDetector._async_process_event().
        """
        self._stats["enrich_calls"] += 1
        self.record_phase_delta(phase, delta_w)

        matches = self._apply_anchor_filter(matches, phase)
        matches = self._apply_context_priors(matches, delta_w, phase, timestamp)

        hint = self._phase_balance_hint(phase, delta_w)
        if hint:
            matches = self._apply_phase_balance(matches, hint)
            self._stats["phase_balance_hints"] += 1

        matches.sort(key=lambda x: x["confidence"], reverse=True)
        return matches

    # ── Anker-apparaten ───────────────────────────────────────────────────────

    def get_anchored_devices(self) -> List[dict]:
        """Geeft actieve anker-apparaten terug als NILM-device-dicts (100% confidence)."""
        return [
            {
                "device_id":     f"__hybrid_{a.plug_id}__",
                "device_type":   a.device_type,
                "name":          a.name,
                "confidence":    1.0,
                "current_power": a.power_w if a.is_on else 0.0,
                "is_on":         a.is_on,
                "source":        "smart_plug",
                "phase":         a.phase,
                "phase_confirmed": a.phase_confirmed,
                "confirmed":     True,
                "user_feedback": "correct",
                # v1.17.3: zodat apparaten ook zichtbaar zijn in stand-by in de NILM-kaart
                "on_events":     max(a.on_events, 1),  # minstens 1: ontdekt = gezien
                "power_min":     round(a.power_max_w, 1),
                "entity_id":     a.entity_id,
            }
            for a in self._anchors.values()
            if not a.is_stale
        ]

    def get_anchored_power_per_phase(self) -> Dict[str, float]:
        """Totaal geankersd vermogen per fase — voor restsignaal-berekening."""
        totals: Dict[str, float] = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
        for a in self._anchors.values():
            if a.is_stale or not a.is_on:
                continue
            if a.phase == "ALL":
                for ph in totals:
                    totals[ph] += a.power_w / 3.0
            elif a.phase in totals:
                totals[a.phase] += a.power_w
        return totals

    def get_diagnostics(self) -> dict:
        active_anchors = [
            {
                "entity_id":       a.entity_id,
                "name":            a.name,
                "device_type":     a.device_type,
                "phase":           a.phase,
                "phase_confirmed": a.phase_confirmed,
                "phase_confirmed_age_h": round((time.time() - a.phase_confirmed_at) / 3600, 1)
                                         if a.phase_confirmed_at > 0 else None,
                "phase_candidate": a.phase_last_candidate,
                "phase_streak":    a.phase_confirm_count,
                "power_w":         round(a.power_w, 1),
                "is_on":           a.is_on,
            }
            for a in self._anchors.values() if not a.is_stale
        ]
        weather_sensors = [
            {"type": w.sensor_type, "entity_id": w.entity_id}
            for w in (self._discovery._last_result.weather
                      if self._discovery._last_result else [])
        ]
        return {
            "anchors_total":         len(self._anchors),
            "anchors_active":        sum(1 for a in self._anchors.values()
                                         if a.is_on and not a.is_stale),
            "anchors_phase_confirmed": sum(1 for a in self._anchors.values()
                                           if a.phase_confirmed),
            "weather_temperature_c": self._weather.temperature_c,
            "weather_season":        self._weather.season,
            "weather_irradiance_w":  self._weather.irradiance_wm2,
            "anchors":               active_anchors,
            "weather_sensors":       weather_sensors,
            "stats":                 dict(self._stats),
        }

    # ── Stap 1: Ankering ──────────────────────────────────────────────────────

    def _apply_anchor_filter(self, matches: List[dict], event_phase: str) -> List[dict]:
        """Verlaag confidentie van types die al door een actief anker gedekt worden."""
        anchored: Dict[str, set] = {}
        for a in self._anchors.values():
            if a.is_stale or not a.is_on:
                continue
            phases = ["L1", "L2", "L3"] if a.phase == "ALL" else [a.phase]
            for ph in phases:
                anchored.setdefault(ph, set()).add(a.device_type)

        blocked = anchored.get(event_phase, set())
        if not blocked:
            return matches

        out = []
        for m in matches:
            if m.get("device_type", "") in blocked:
                m = {**m, "confidence": m["confidence"] * 0.15,
                     "hybrid_note": "anchored_excluded"}
                self._stats["anchor_hits"] += 1
            out.append(m)
        return out

    # ── Stap 2: Contextpriors ─────────────────────────────────────────────────

    def _apply_context_priors(
        self, matches: List[dict], delta_w: float, phase: str, timestamp: float
    ) -> List[dict]:
        now       = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        hour      = now.hour
        wday      = now.weekday()
        abs_delta = abs(delta_w)
        wx        = self._weather

        out = []
        for m in matches:
            dt   = m.get("device_type", "")
            conf = m["confidence"]
            note = m.get("hybrid_note", "")
            f    = 1.0   # multiplicatieve factor

            # ── Temperatuurpriors ─────────────────────────────────────────
            if dt == "heat_pump":
                f *= 1.30 if wx.is_cold else (1.20 if wx.is_hot else 0.85)
            elif dt == "boiler":
                f *= 1.20 if wx.is_cold else (0.75 if wx.is_hot else 1.0)
            elif dt in ("cv_boiler", "electric_heater"):
                if wx.season == "summer": f *= 0.40

            # ── Tijdstippriors ────────────────────────────────────────────
            if dt == "washing_machine":
                f *= 0.30 if 0 <= hour < 6 else (1.10 if 6 <= hour < 22 else 0.80)
            elif dt == "dishwasher":
                f *= 0.25 if 0 <= hour < 5 else (1.20 if 18 <= hour <= 23 else 1.0)
            elif dt == "microwave":
                meal = (7 <= hour <= 9) or (12 <= hour <= 14) or (17 <= hour <= 20)
                f *= 1.15 if meal else (0.20 if 0 <= hour < 5 else 1.0)
            elif dt == "kettle":
                f *= 1.25 if (7 <= hour <= 9 or 15 <= hour <= 17) else \
                     (0.15 if 0 <= hour < 5 else 1.0)
            elif dt == "light":
                f *= 1.20 if (6 <= hour < 8 or 17 <= hour <= 23) else \
                     (0.70 if 10 <= hour <= 16 else 1.0)
            elif dt == "ev_charger":
                f *= 1.20 if (0 <= hour < 8 or 18 <= hour <= 23) else 0.80

            # ── Weekend-effect ────────────────────────────────────────────
            if dt == "washing_machine" and wday >= 5:
                f *= 1.15

            # ── Seizoenspriors ────────────────────────────────────────────
            if dt == "heat_pump" and wx.season in ("spring", "summer") and wx.temperature_c < 20:
                f *= 0.70

            # ── Vermogensbereik ───────────────────────────────────────────
            big_types   = {"washing_machine", "dryer", "dishwasher", "boiler",
                           "heat_pump", "ev_charger", "oven"}
            small_types = {"refrigerator", "microwave", "kettle", "light",
                           "entertainment", "socket"}
            if abs_delta < 100 and dt in big_types:
                f *= 0.40
            if abs_delta > 5000 and dt in small_types:
                f *= 0.30

            # ── Toepassen ─────────────────────────────────────────────────
            f       = max(PRIOR_MAX_PENALTY, min(PRIOR_MAX_BOOST, f))
            new_c   = round(max(0.0, min(1.0, conf * f)), 4)

            if f > 1.01:
                self._stats["prior_boosts"] += 1
                note = (note + ",prior_boost").lstrip(",")
            elif f < 0.99:
                self._stats["prior_penalties"] += 1
                note = (note + ",prior_penalty").lstrip(",")

            out.append({**m, "confidence": new_c,
                        "hybrid_note": note, "prior_factor": round(f, 3)})
        return out

    # ── Stap 3: 3-fase balans ─────────────────────────────────────────────────

    def _phase_balance_hint(self, event_phase: str, event_delta_w: float) -> Optional[str]:
        if abs(event_delta_w) < PHASE_MIN_DELTA_W:
            return None
        now    = time.time()
        recent = {event_phase: event_delta_w}
        for ph, snap in self._phase_snapshots.items():
            if ph != event_phase and (now - snap.timestamp) < PHASE_WIN_S:
                recent[ph] = snap.delta_w
        if len(recent) < 3:
            return None
        total = sum(abs(dw) for dw in recent.values())
        if total < PHASE_MIN_DELTA_W:
            return None
        ratio = abs(event_delta_w) / total
        if PHASE_RATIO_MIN <= ratio <= PHASE_RATIO_MAX:
            same_dir = all((dw > 0) == (event_delta_w > 0)
                          for dw in recent.values() if abs(dw) > 50)
            if same_dir:
                return "three_phase"
        return "single_phase"

    def _apply_phase_balance(self, matches: List[dict], hint: str) -> List[dict]:
        out = []
        for m in matches:
            dt   = m.get("device_type", "")
            conf = m["confidence"]
            note = m.get("hybrid_note", "")
            if hint == "three_phase":
                if dt in THREE_PHASE_TYPES:
                    conf = min(1.0, conf * 1.25)
                    note = (note + ",3ph_boost").lstrip(",")
                else:
                    conf *= 0.70
                    note = (note + ",3ph_penalty").lstrip(",")
            else:  # single_phase
                if dt in THREE_PHASE_TYPES:
                    conf *= 0.65
                    note = (note + ",1ph_penalty").lstrip(",")
                else:
                    conf = min(1.0, conf * 1.15)
                    note = (note + ",1ph_boost").lstrip(",")
            out.append({**m, "confidence": round(conf, 4), "hybrid_note": note})
        return out
