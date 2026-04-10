# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
system_quality.py — v4.6.533

Vier modules voor systeemkwaliteit en operationele integriteit:

1. BDEDecisionQualityTracker
   Beoordeelt of BDE-laad/ontlaad-beslissingen achteraf de juiste keuzes waren.

2. ShutterComfortLearner
   Leert het gewenste sluittijdstip per kamer uit handmatige overrides.

3. IntegrationLatencyMonitor
   Meet update-frequentie en latency per gekoppelde integratie.

4. P1TelegramQualityMonitor
   Analyseert P1-telegram patronen op fouten, gaps en consistentie.

Alle modules hebben cloud-sync via CloudSyncMixin.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .cloud_sync_mixin import CloudSyncMixin

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
EMA_ALPHA = 0.10
SAVE_INTERVAL = 30


# ─────────────────────────────────────────────────────────────────────────────
# 1. BDEDecisionQualityTracker
# ─────────────────────────────────────────────────────────────────────────────

STORAGE_KEY_BDE = "cloudems_bde_quality_v1"
BDE_EVAL_WINDOW_H = 4     # beoordeel beslissing na 4 uur
BDE_MIN_SAMPLES   = 20


@dataclass
class BDEDecision:
    """Één BDE-beslissing met achteraf-evaluatie."""
    ts:            float
    action:        str      # "charge" / "discharge" / "hold"
    price_eur_kwh: float
    soc_pct:       float
    outcome_price: Optional[float] = None   # gemiddelde prijs in volgend venster
    evaluated:     bool            = False

    def to_dict(self) -> dict:
        return {
            "ts": round(self.ts),
            "action": self.action,
            "price": round(self.price_eur_kwh, 4),
            "soc": round(self.soc_pct, 1),
            "outcome": round(self.outcome_price, 4) if self.outcome_price else None,
            "evaluated": self.evaluated,
        }


class BDEDecisionQualityTracker(CloudSyncMixin):
    """
    Vergelijkt BDE-beslissingen met de achteraf-optimale keuze.
    Laad je op het goedkoopste uur? Ontlaad je op het duurste?
    Leert een efficiëntiescore 0-100%.
    """

    _cloud_module_name = "bde_decision_quality"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        self._pending: deque[BDEDecision] = deque(maxlen=200)
        self._ema_quality: float = 0.5    # prior: 50%
        self._sample_count: int  = 0
        self._store = None
        self._dirty_count = 0
        # Rollend venster van prijzen voor achteraf-evaluatie
        self._price_history: deque = deque(maxlen=48)   # 8 uur bij 10 min

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_BDE)
        data = await self._store.async_load()
        if data:
            self._ema_quality  = float(data.get("ema_quality", 0.5))
            self._sample_count = int(data.get("samples", 0))

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save({
                "ema_quality": round(self._ema_quality, 4),
                "samples":     self._sample_count,
            })
            self._dirty_count = 0

    def record_decision(
        self,
        action: str,
        price_eur_kwh: float,
        soc_pct: float,
    ) -> None:
        """Registreer een BDE-beslissing voor latere evaluatie."""
        self._pending.append(BDEDecision(
            ts=time.time(),
            action=action,
            price_eur_kwh=price_eur_kwh,
            soc_pct=soc_pct,
        ))

    def tick(self, current_price_eur_kwh: float) -> None:
        """
        Elke cyclus aanroepen met huidige prijs.
        Evalueert rijpe beslissingen.
        """
        now = time.time()
        self._price_history.append((now, current_price_eur_kwh))

        for dec in self._pending:
            if dec.evaluated:
                continue
            age_h = (now - dec.ts) / 3600
            if age_h < BDE_EVAL_WINDOW_H:
                continue

            # Bereken gemiddelde prijs in venster ná de beslissing
            window_prices = [
                p for ts, p in self._price_history
                if dec.ts <= ts <= dec.ts + BDE_EVAL_WINDOW_H * 3600
            ]
            if not window_prices:
                dec.evaluated = True
                continue

            outcome_avg = sum(window_prices) / len(window_prices)
            dec.outcome_price = outcome_avg
            dec.evaluated = True

            # Beoordeel kwaliteit
            quality = self._score_decision(dec, outcome_avg)
            self._ema_quality  = EMA_ALPHA * quality + (1 - EMA_ALPHA) * self._ema_quality
            self._sample_count += 1
            self._dirty_count  += 1

            self._log_decision(dec, quality)

    def _score_decision(self, dec: BDEDecision, outcome_avg: float) -> float:
        """
        Score 0-1: hoe goed was de beslissing achteraf?
        charge bij lage prijs → goed als uitkomst hoger is
        discharge bij hoge prijs → goed als uitkomst lager is
        """
        if dec.action == "charge":
            # Goed als we goedkoop hebben geladen (prijs was lager dan toekomst)
            if outcome_avg > dec.price_eur_kwh:
                return min(1.0, (outcome_avg - dec.price_eur_kwh) / max(outcome_avg, 0.01))
            else:
                return max(0.0, 0.5 - (dec.price_eur_kwh - outcome_avg) / max(dec.price_eur_kwh, 0.01))
        elif dec.action == "discharge":
            # Goed als we duur hebben ontladen (prijs was hoger dan toekomst)
            if dec.price_eur_kwh > outcome_avg:
                return min(1.0, (dec.price_eur_kwh - outcome_avg) / max(dec.price_eur_kwh, 0.01))
            else:
                return max(0.0, 0.5 - (outcome_avg - dec.price_eur_kwh) / max(outcome_avg, 0.01))
        return 0.5   # hold-beslissingen: neutraal

    def _log_decision(self, dec: BDEDecision, quality: float) -> None:
        if quality < 0.3 and self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "bde_quality",
                    action   = f"{dec.action}_poor",
                    reason   = f"quality={quality:.2f}",
                    message  = (
                        f"BDE beslissing {dec.action} op {dec.price_eur_kwh*100:.1f}ct/kWh "
                        f"achteraf score {quality:.0%} "
                        f"(uitkomst gem. {dec.outcome_price*100:.1f}ct)"
                    ),
                    extra    = {
                        "action":    dec.action,
                        "price_ct":  round(dec.price_eur_kwh * 100, 2),
                        "outcome_ct": round((dec.outcome_price or 0) * 100, 2),
                        "quality":   round(quality, 3),
                        "soc_pct":   round(dec.soc_pct, 1),
                    },
                )
            except Exception:
                pass

    def _get_learned_data(self) -> dict:
        return {
            "ema_quality":  round(self._ema_quality, 3),
            "sample_count": self._sample_count,
        }

    def _apply_prior(self, data: dict) -> None:
        if self._sample_count < BDE_MIN_SAMPLES:
            prior = float(data.get("ema_quality", 0.5))
            self._ema_quality = 0.7 * self._ema_quality + 0.3 * prior

    def get_diagnostics(self) -> dict:
        return {
            "ema_quality_pct": round(self._ema_quality * 100, 1),
            "sample_count":    self._sample_count,
            "pending_evals":   sum(1 for d in self._pending if not d.evaluated),
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. ShutterComfortLearner
# ─────────────────────────────────────────────────────────────────────────────

STORAGE_KEY_SHUTTER = "cloudems_shutter_comfort_v1"
MIN_OVERRIDES = 5   # minimaal 5 handmatige overrides voor betrouwbare uitspraak


@dataclass
class ShutterComfortProfile:
    """Geleerde voorkeurstijden per kamer."""
    room_id:       str
    # {weekday_hour: override_count} — hoe vaak handmatig geopend op dit moment
    open_votes:    Dict[str, int] = field(default_factory=dict)
    close_votes:   Dict[str, int] = field(default_factory=dict)
    total_opens:   int = 0
    total_closes:  int = 0

    def vote_key(self, weekday: int, hour: int) -> str:
        return f"{weekday}_{hour}"

    def record_open_override(self, weekday: int, hour: int) -> None:
        key = self.vote_key(weekday, hour)
        self.open_votes[key] = self.open_votes.get(key, 0) + 1
        self.total_opens += 1

    def record_close_override(self, weekday: int, hour: int) -> None:
        key = self.vote_key(weekday, hour)
        self.close_votes[key] = self.close_votes.get(key, 0) + 1
        self.total_closes += 1

    def preferred_open_slots(self, min_votes: int = MIN_OVERRIDES) -> List[Tuple[int, int]]:
        """Geeft (weekday, hour) slots terug met genoeg open-overrides."""
        result = []
        for key, count in self.open_votes.items():
            if count >= min_votes:
                wd, h = map(int, key.split("_"))
                result.append((wd, h))
        return result

    def to_dict(self) -> dict:
        return {
            "room_id":    self.room_id,
            "open":       self.open_votes,
            "close":      self.close_votes,
            "n_open":     self.total_opens,
            "n_close":    self.total_closes,
        }

    def from_dict(self, d: dict) -> None:
        self.room_id     = d.get("room_id", self.room_id)
        self.open_votes  = d.get("open", {})
        self.close_votes = d.get("close", {})
        self.total_opens  = int(d.get("n_open", 0))
        self.total_closes = int(d.get("n_close", 0))


class ShutterComfortLearner(CloudSyncMixin):
    """
    Leert comfort-voorkeurstijden voor rolluiken per kamer
    op basis van handmatige overrides.
    """

    _cloud_module_name = "shutter_comfort"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        self._profiles: Dict[str, ShutterComfortProfile] = {}
        self._store = None
        self._dirty_count = 0

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_SHUTTER)
        data = await self._store.async_load()
        if data:
            for room_id, d in data.items():
                p = ShutterComfortProfile(room_id=room_id)
                p.from_dict(d)
                self._profiles[room_id] = p

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save(
                {k: v.to_dict() for k, v in self._profiles.items()}
            )
            self._dirty_count = 0

    def record_manual_open(self, room_id: str, weekday: int, hour: int) -> None:
        """Registreer handmatig openen — gebruiker override op automatisch sluiten."""
        if room_id not in self._profiles:
            self._profiles[room_id] = ShutterComfortProfile(room_id=room_id)
        self._profiles[room_id].record_open_override(weekday, hour)
        self._dirty_count += 1
        _LOGGER.debug("ShutterComfort: open override %s wd=%d h=%d", room_id, weekday, hour)

    def record_manual_close(self, room_id: str, weekday: int, hour: int) -> None:
        """Registreer handmatig sluiten — gebruiker override op automatisch open."""
        if room_id not in self._profiles:
            self._profiles[room_id] = ShutterComfortProfile(room_id=room_id)
        self._profiles[room_id].record_close_override(weekday, hour)
        self._dirty_count += 1

    def get_preferred_open_slots(self, room_id: str) -> List[Tuple[int, int]]:
        """Geeft geleerde voorkeurs-open-slots voor een kamer."""
        p = self._profiles.get(room_id)
        return p.preferred_open_slots() if p else []

    def should_suppress_auto_close(
        self, room_id: str, weekday: int, hour: int
    ) -> bool:
        """
        Geeft True als de gebruiker op dit tijdstip structureel handmatig opent.
        Gebruikt door ShutterController om automatisch sluiten te onderdrukken.
        """
        p = self._profiles.get(room_id)
        if not p:
            return False
        key = p.vote_key(weekday, hour)
        return p.open_votes.get(key, 0) >= MIN_OVERRIDES

    def _get_learned_data(self) -> dict:
        """Cloud-sync: anoniem patroon van open/dicht per dag-uur bucket."""
        hour_open_totals: Dict[str, int] = {}
        for p in self._profiles.values():
            for key, count in p.open_votes.items():
                hour_open_totals[key] = hour_open_totals.get(key, 0) + count
        return {"hour_open_totals": hour_open_totals}

    def _apply_prior(self, data: dict) -> None:
        pass   # Shutter-voorkeur is sterk persoonlijk — geen prior zinvol

    def get_diagnostics(self) -> dict:
        return {
            room_id: {
                "total_opens":   p.total_opens,
                "total_closes":  p.total_closes,
                "preferred_open_slots": p.preferred_open_slots(),
            }
            for room_id, p in self._profiles.items()
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. IntegrationLatencyMonitor
# ─────────────────────────────────────────────────────────────────────────────

STORAGE_KEY_LATENCY = "cloudems_integration_latency_v1"
LATENCY_WARN_S      = 30    # >30s tussen updates = langzaam
LATENCY_ALERT_S     = 120   # >120s = mogelijke storing


class IntegrationLatencyMonitor(CloudSyncMixin):
    """
    Meet update-frequentie en latency per gekoppelde integratie.
    Detecteert als cloud-APIs trager of minder betrouwbaar worden.
    """

    _cloud_module_name = "integration_latency"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        # {integration_name: {"last_ts": float, "ema_interval_s": float,
        #                      "samples": int, "alert_sent": bool}}
        self._state: Dict[str, dict] = {}
        self._store = None
        self._dirty_count = 0

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_LATENCY)
        data = await self._store.async_load()
        if data:
            for name, d in data.items():
                self._state[name] = {
                    "last_ts":         float(d.get("last_ts", 0)),
                    "ema_interval_s":  float(d.get("ema_s", 10.0)),
                    "samples":         int(d.get("samples", 0)),
                    "alert_sent":      False,
                }

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save({
                name: {
                    "last_ts": round(s["last_ts"]),
                    "ema_s":   round(s["ema_interval_s"], 2),
                    "samples": s["samples"],
                }
                for name, s in self._state.items()
            })
            self._dirty_count = 0

    def record_update(self, integration_name: str) -> None:
        """Registreer een data-update van een integratie."""
        now = time.time()
        if integration_name not in self._state:
            self._state[integration_name] = {
                "last_ts":        now,
                "ema_interval_s": 10.0,
                "samples":        0,
                "alert_sent":     False,
            }
            return

        s = self._state[integration_name]
        if s["last_ts"] > 0:
            interval = now - s["last_ts"]
            if 0.5 < interval < 600:   # plausibel bereik
                s["ema_interval_s"] = EMA_ALPHA * interval + (1 - EMA_ALPHA) * s["ema_interval_s"]
                s["samples"] += 1
                self._dirty_count += 1

                # Reset alert als het weer snel is
                if interval < LATENCY_WARN_S * 2:
                    s["alert_sent"] = False

        s["last_ts"] = now

    STARTUP_GRACE_S = 300  # 5 minuten grace na herstart — omvormers hebben tijd nodig

    def check_stale(self) -> List[dict]:
        """Controleer of integraties nog actief zijn. Aanroepen elke cyclus."""
        now = time.time()
        # v5.5.345: grace period na herstart — na boot zijn alle sensoren "stale"
        # omdat last_ts uit vorige run is geladen. Wacht 5 minuten voor eerste check.
        if now - self._start_ts < self.STARTUP_GRACE_S:
            return []
        issues = []
        for name, s in self._state.items():
            if s["last_ts"] <= 0 or s["samples"] < 5:
                continue
            age = now - s["last_ts"]
            threshold = max(LATENCY_WARN_S, s["ema_interval_s"] * 3)
            if age > threshold and not s["alert_sent"]:
                s["alert_sent"] = True
                level = "alert" if age > LATENCY_ALERT_S else "warning"
                issues.append({
                    "integration": name,
                    "age_s":       round(age),
                    "normal_s":    round(s["ema_interval_s"], 1),
                    "level":       level,
                })
                self._emit_hint(name, age, s["ema_interval_s"])
                self._log(name, age, s["ema_interval_s"])
        return issues

    def _emit_hint(self, name: str, age_s: float, normal_s: float) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"integration_latency_{name.replace('.', '_')}",
                title      = f"Integratie reageert traag: {name}",
                message    = (
                    f"Integratie '{name}' heeft al {age_s/60:.0f} minuten geen update gestuurd "
                    f"(normaal elke {normal_s:.0f}s). "
                    f"CloudEMS gebruikt mogelijk verouderde data voor sturing. "
                    f"Controleer de integratie in HA."
                ),
                action     = f"Controleer integratie '{name}' in HA",
                confidence = min(0.90, age_s / LATENCY_ALERT_S),
            )
        except Exception as _e:
            _LOGGER.debug("IntegrationLatency hint fout: %s", _e)

    def _log(self, name: str, age_s: float, normal_s: float) -> None:
        msg = (
            f"IntegrationLatencyMonitor: '{name}' is {age_s:.0f}s stil "
            f"(normaal {normal_s:.0f}s)"
        )
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "integration_latency",
                    action   = "stale_integration",
                    reason   = name,
                    message  = msg,
                    extra    = {
                        "integration": name,
                        "age_s":       round(age_s),
                        "normal_s":    round(normal_s, 1),
                    },
                )
            except Exception:
                pass

    def _get_learned_data(self) -> dict:
        return {
            name: {"ema_interval_s": self._round_for_cloud(s["ema_interval_s"]),
                   "samples": s["samples"]}
            for name, s in self._state.items()
            if s["samples"] >= 10
        }

    def get_diagnostics(self) -> dict:
        now = time.time()
        return {
            name: {
                "ema_interval_s": round(s["ema_interval_s"], 1),
                "age_s":          round(now - s["last_ts"]) if s["last_ts"] > 0 else None,
                "samples":        s["samples"],
            }
            for name, s in self._state.items()
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4. P1TelegramQualityMonitor
# ─────────────────────────────────────────────────────────────────────────────

STORAGE_KEY_P1 = "cloudems_p1_quality_v1"
P1_GAP_WARN_S   = 30    # >30s geen telegram = gap
P1_GAP_ALERT_S  = 120   # >120s = storing
P1_SPIKE_FRAC   = 3.0   # waarde >3× EMA = spike
P1_FROZEN_FRAC  = 0.02  # <2% variatie over 60 samples = bevroren


class P1TelegramQualityMonitor(CloudSyncMixin):
    """
    Analyseert P1-telegram kwaliteit: gaps, spikes, bevroren waarden,
    inconsistente velden.
    """

    _cloud_module_name = "p1_telegram_quality"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        self._last_telegram_ts:  float = 0.0
        self._ema_interval_s:    float = 10.0
        self._total_telegrams:   int   = 0
        self._total_gaps:        int   = 0
        self._total_spikes:      int   = 0
        self._quality_score:     float = 1.0   # 0-1
        self._store = None
        self._dirty_count = 0
        # {field: {"ema": float, "samples": int, "spikes": int}}
        self._field_stats: Dict[str, dict] = {}
        # Ringbuffer laatste 60 net-vermogen waarden voor bevroren-detectie
        self._net_power_buf: deque = deque(maxlen=60)
        self._alert_sent_gap:    bool = False
        self._alert_sent_frozen: bool = False

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_P1)
        data = await self._store.async_load()
        if data:
            self._ema_interval_s  = float(data.get("ema_interval_s", 10.0))
            self._total_telegrams = int(data.get("total_telegrams", 0))
            self._total_gaps      = int(data.get("total_gaps", 0))
            self._total_spikes    = int(data.get("total_spikes", 0))
            self._quality_score   = float(data.get("quality_score", 1.0))

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save({
                "ema_interval_s":  round(self._ema_interval_s, 2),
                "total_telegrams": self._total_telegrams,
                "total_gaps":      self._total_gaps,
                "total_spikes":    self._total_spikes,
                "quality_score":   round(self._quality_score, 4),
            })
            self._dirty_count = 0

    def record_telegram(
        self,
        net_power_w: float,
        fields: Optional[Dict[str, float]] = None,
    ) -> dict:
        """
        Verwerk één P1-telegram.
        Geeft kwaliteitsinfo terug.
        """
        now = time.time()
        issues = []

        # Interval meten
        if self._last_telegram_ts > 0:
            interval = now - self._last_telegram_ts
            if 0.5 < interval < 300:
                self._ema_interval_s = EMA_ALPHA * interval + (1 - EMA_ALPHA) * self._ema_interval_s

            # Gap detectie
            if interval > P1_GAP_WARN_S:
                self._total_gaps += 1
                issues.append({"type": "gap", "age_s": round(interval)})
                if interval > P1_GAP_ALERT_S and not self._alert_sent_gap:
                    self._alert_sent_gap = True
                    self._emit_hint("gap", interval)
                    self._log("gap", f"{interval:.0f}s geen telegram")
            else:
                self._alert_sent_gap = False

        self._last_telegram_ts = now
        self._total_telegrams += 1
        self._net_power_buf.append(net_power_w)
        self._dirty_count += 1

        # Spike detectie op nettovermogen
        if self._total_telegrams > 20 and self._ema_interval_s > 0:
            ema_p = sum(self._net_power_buf) / len(self._net_power_buf)
            if abs(net_power_w) > max(abs(ema_p) * P1_SPIKE_FRAC, 5000):
                self._total_spikes += 1
                issues.append({"type": "spike", "value_w": round(net_power_w)})

        # Bevroren detectie
        if len(self._net_power_buf) >= 60:
            buf_list = list(self._net_power_buf)
            mean = sum(buf_list) / len(buf_list)
            std  = (sum((x - mean) ** 2 for x in buf_list) / len(buf_list)) ** 0.5
            cv   = std / max(abs(mean), 1.0)
            if cv < P1_FROZEN_FRAC and abs(mean) > 50 and not self._alert_sent_frozen:
                self._alert_sent_frozen = True
                issues.append({"type": "frozen", "cv": round(cv, 4)})
                self._emit_hint("frozen", 0)
                self._log("frozen", f"CV={cv:.4f}")
            elif cv > P1_FROZEN_FRAC * 5:
                self._alert_sent_frozen = False

        # Veld-spike detectie
        if fields:
            for field_name, value in fields.items():
                if value is None:
                    continue
                fs = self._field_stats.setdefault(field_name, {"ema": value, "samples": 0, "spikes": 0})
                if fs["samples"] > 10 and abs(value) > abs(fs["ema"]) * P1_SPIKE_FRAC and abs(value) > 100:
                    fs["spikes"] += 1
                    issues.append({"type": f"field_spike_{field_name}", "value": round(value)})
                fs["ema"] = EMA_ALPHA * value + (1 - EMA_ALPHA) * fs["ema"]
                fs["samples"] = min(fs["samples"] + 1, 9999)

        # Update kwaliteitsscore
        spike_rate = self._total_spikes / max(self._total_telegrams, 1)
        gap_rate   = self._total_gaps   / max(self._total_telegrams, 1)
        self._quality_score = max(0.0, 1.0 - spike_rate * 5 - gap_rate * 3)

        return {
            "quality_score":     round(self._quality_score, 3),
            "ema_interval_s":    round(self._ema_interval_s, 1),
            "total_telegrams":   self._total_telegrams,
            "total_gaps":        self._total_gaps,
            "total_spikes":      self._total_spikes,
            "issues_this_cycle": issues,
        }

    def _emit_hint(self, problem: str, value: float) -> None:
        if not self._hint_engine:
            return
        messages = {
            "gap": (
                f"P1-slimme meter heeft al {value:.0f}s geen telegram gestuurd. "
                f"CloudEMS werkt met verouderde netdata. "
                f"Controleer de P1-kabelverbinding of USB-adapter."
            ),
            "frozen": (
                f"P1-netmeting lijkt bevroren — waarde varieert nauwelijks "
                f"terwijl er normaal vermogensschommelingen zouden zijn. "
                f"Controleer de P1-verbinding."
            ),
        }
        msg = messages.get(problem)
        if not msg:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"p1_quality_{problem}",
                title      = f"P1-kwaliteitsproблeem: {problem}",
                message    = msg,
                action     = "Controleer P1-kabelverbinding en USB-adapter",
                confidence = 0.85,
            )
        except Exception as _e:
            _LOGGER.debug("P1Quality hint fout: %s", _e)

    def _log(self, problem: str, detail: str) -> None:
        msg = f"P1TelegramQualityMonitor: {problem} — {detail}"
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "p1_quality",
                    action   = problem,
                    reason   = detail,
                    message  = msg,
                    extra    = {
                        "problem": problem,
                        "detail":  detail,
                        "quality_score": round(self._quality_score, 3),
                    },
                )
            except Exception:
                pass

    def _get_learned_data(self) -> dict:
        return {
            "ema_interval_s": self._round_for_cloud(self._ema_interval_s),
            "quality_score":  round(self._quality_score, 3),
            "spike_rate":     round(self._total_spikes / max(self._total_telegrams, 1), 4),
            "gap_rate":       round(self._total_gaps   / max(self._total_telegrams, 1), 4),
        }

    def get_diagnostics(self) -> dict:
        return {
            "quality_score":    round(self._quality_score, 3),
            "ema_interval_s":   round(self._ema_interval_s, 1),
            "total_telegrams":  self._total_telegrams,
            "total_gaps":       self._total_gaps,
            "total_spikes":     self._total_spikes,
            "field_stats": {
                k: {"spikes": v["spikes"], "samples": v["samples"]}
                for k, v in self._field_stats.items()
                if v["samples"] > 0
            },
        }
