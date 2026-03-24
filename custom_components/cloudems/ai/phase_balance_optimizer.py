"""
CloudEMS Phase Balance Optimizer — v1.0.0

Predictive phase balance: learns load patterns and warns BEFORE imbalance occurs.
"""
from __future__ import annotations
import logging, math, time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)
STORAGE_KEY     = "cloudems_phase_balance_v1"
STORAGE_VERSION = 1
MIN_SAMPLES        = 144
MAX_HISTORY        = 5000
from ..const import PHASE_IMBALANCE_THRESHOLD_A as IMBALANCE_THRESHOLD_A


@dataclass
class PhaseSample:
    ts: float; hour: int; minute: int; dow: int
    l1_a: float; l2_a: float; l3_a: float
    active_labels: list = field(default_factory=list)


@dataclass
class PhaseLoadForecast:
    l1_a: list; l2_a: list; l3_a: list
    slots_minutes: list
    warning_phase:  Optional[str]
    warning_in_min: Optional[float]
    warning_a:      Optional[float]
    confidence:     float


class PhaseBalanceOptimizer:
    """Predictive phase balance optimizer."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass   = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._samples: deque = deque(maxlen=MAX_HISTORY)
        self._hourly_profile: dict = {h: {"L1":0.0,"L2":0.0,"L3":0.0} for h in range(24)}
        self._appliance_phase: dict = {}
        self._imbalance_start_ts: Optional[float] = None
        self._imbalance_start_l:  tuple = (0.0, 0.0, 0.0)
        self._n_imbalance_events  = 0
        self._dirty = False

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for h_str, phases in saved.get("hourly_profile", {}).items():
            h = int(h_str)
            if h in self._hourly_profile:
                self._hourly_profile[h].update(phases)
        self._appliance_phase = saved.get("appliance_phase", {})
        for s in saved.get("samples", [])[-500:]:
            try: self._samples.append(PhaseSample(**s))
            except Exception: pass
        _LOGGER.info("Phase Balance Optimizer: %d samples, %d appliances", len(self._samples), len(self._appliance_phase))

    def tick(self, l1_a: float, l2_a: float, l3_a: float,
             active_devices: Optional[list] = None, ts: Optional[float] = None) -> Optional[str]:
        ts  = ts or time.time()
        now = datetime.fromtimestamp(ts, tz=timezone.utc)
        labels = [d.get("label","") for d in (active_devices or []) if d.get("label")]
        self._samples.append(PhaseSample(ts=ts, hour=now.hour, minute=now.minute,
            dow=now.weekday(), l1_a=l1_a, l2_a=l2_a, l3_a=l3_a, active_labels=labels))
        # Update hourly profile (EMA)
        alpha = 0.02
        for ph, val in [("L1",l1_a),("L2",l2_a),("L3",l3_a)]:
            old = self._hourly_profile[now.hour][ph]
            self._hourly_profile[now.hour][ph] = old*(1-alpha) + val*alpha
        if labels:
            self._update_appliance_phase(labels, l1_a, l2_a, l3_a)
        self._track_imbalance(l1_a, l2_a, l3_a, ts)
        self._dirty = True
        if len(self._samples) < MIN_SAMPLES:
            return None
        # Quick warning
        vals = [l1_a, l2_a, l3_a]
        if max(vals) - min(vals) > IMBALANCE_THRESHOLD_A * 1.5:
            heavy = ["L1","L2","L3"][vals.index(max(vals))]
            return f"Fase-onbalans: {heavy}={max(vals):.1f}A, delta={max(vals)-min(vals):.1f}A"
        return None

    def forecast(self, horizon_min: int = 30) -> PhaseLoadForecast:
        now   = datetime.now(timezone.utc)
        slots = list(range(0, horizon_min+1, 5))
        l1_fc, l2_fc, l3_fc = [], [], []
        for slot_min in slots:
            fh = (now.hour + (now.minute + slot_min)//60) % 24
            p  = self._hourly_profile[fh]
            l1_fc.append(round(p["L1"],2))
            l2_fc.append(round(p["L2"],2))
            l3_fc.append(round(p["L3"],2))
        warning_phase = warning_in = warning_a = None
        for i, sm in enumerate(slots):
            v = [l1_fc[i], l2_fc[i], l3_fc[i]]
            if max(v)-min(v) > IMBALANCE_THRESHOLD_A and warning_phase is None:
                warning_phase = ["L1","L2","L3"][v.index(max(v))]
                warning_in    = float(sm)
                warning_a     = max(v)
        return PhaseLoadForecast(l1_a=l1_fc, l2_a=l2_fc, l3_a=l3_fc,
            slots_minutes=slots, warning_phase=warning_phase,
            warning_in_min=warning_in, warning_a=warning_a,
            confidence=min(0.85, len(self._samples)/1000.0))

    def recommend_ev_phase(self, l1: float, l2: float, l3: float) -> dict:
        loads   = {"L1":l1,"L2":l2,"L3":l3}
        lightest = min(loads, key=loads.get)
        heaviest = max(loads, key=loads.get)
        delta    = loads[heaviest] - loads[lightest]
        if delta < IMBALANCE_THRESHOLD_A:
            return {"phase":None,"reason":"Fasen in balans","confidence":0.5}
        return {"phase":lightest,
                "reason":f"EV op {lightest} laden verbetert balans ({heaviest}={loads[heaviest]:.1f}A vs {lightest}={loads[lightest]:.1f}A)",
                "confidence":min(0.9, delta/10.0)}

    def _update_appliance_phase(self, labels, l1, l2, l3):
        for label in labels:
            if label not in self._appliance_phase:
                self._appliance_phase[label] = {"L1":0.0,"L2":0.0,"L3":0.0,"n":0}
            d = self._appliance_phase[label]; alpha = 0.05
            d["L1"] = d["L1"]*(1-alpha)+l1*alpha
            d["L2"] = d["L2"]*(1-alpha)+l2*alpha
            d["L3"] = d["L3"]*(1-alpha)+l3*alpha
            d["n"]  = d.get("n",0)+1

    def _track_imbalance(self, l1, l2, l3, ts):
        vals  = [l1, l2, l3]
        is_imb = max(vals)-min(vals) > IMBALANCE_THRESHOLD_A
        if is_imb and self._imbalance_start_ts is None:
            self._imbalance_start_ts = ts
            self._imbalance_start_l  = (l1, l2, l3)
        elif not is_imb and self._imbalance_start_ts is not None:
            self._n_imbalance_events += 1
            self._imbalance_start_ts  = None

    async def async_maybe_save(self) -> None:
        if self._dirty: await self._save()

    async def async_save(self) -> None:
        await self._save()

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "hourly_profile": self._hourly_profile,
                "appliance_phase": self._appliance_phase,
                "samples": [{"ts":s.ts,"hour":s.hour,"minute":s.minute,"dow":s.dow,
                    "l1_a":s.l1_a,"l2_a":s.l2_a,"l3_a":s.l3_a,"active_labels":s.active_labels}
                    for s in list(self._samples)[-500:]],
            })
            self._dirty = False
        except Exception as exc:
            _LOGGER.warning("Phase Balance save error: %s", exc)

    @property
    def stats(self) -> dict:
        fc = self.forecast(15) if len(self._samples) >= MIN_SAMPLES else None
        return {"n_samples":len(self._samples),"ready":len(self._samples)>=MIN_SAMPLES,
            "n_appliances":len(self._appliance_phase),
            "n_imbalance_events":self._n_imbalance_events,
            "warning_phase":fc.warning_phase if fc else None,
            "warning_in_min":fc.warning_in_min if fc else None,
            "confidence":fc.confidence if fc else 0.0}
