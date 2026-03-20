# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
inverter_efficiency.py — v4.6.531

Leert het DC→AC rendement per omvormer op basis van gemeten DC- en AC-vermogen.

Verwacht rendement: 94–98% bij normaal bedrijf.
Afwijkingen duiden op:
  - Verkeerd rated_power ingesteld
  - Clipping die niet gemeld wordt
  - Omvormer defect of degradatie
  - Verkeerde sensor gekoppeld (DC-sensor van verkeerde string)

Zelflerend via EMA per vermogensbereik (laag/midden/hoog).
Meldingen via hint_engine.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_inverter_efficiency_v1"
STORAGE_VERSION = 1

EMA_ALPHA     = 0.08
MIN_SAMPLES   = 20
SAVE_INTERVAL = 60

EFF_MIN_NORMAL  = 0.92   # onder dit = waarschuwing
EFF_MIN_ALERT   = 0.85   # onder dit = alert
EFF_MAX_NORMAL  = 1.02   # boven dit = sensor-probleem (meting > 100%)
MIN_DC_W        = 100    # minimaal DC-vermogen voor betrouwbare meting


@dataclass
class InverterEffState:
    ema_efficiency: float = 0.96   # prior: 96%
    sample_count:   int   = 0
    classification: str   = "learning"
    confidence:     float = 0.0
    min_seen:       float = 1.0
    max_seen:       float = 0.0

    def to_dict(self) -> dict:
        return {
            "ema_eff":  round(self.ema_efficiency, 4),
            "samples":  self.sample_count,
            "class":    self.classification,
            "conf":     round(self.confidence, 4),
            "min":      round(self.min_seen, 4),
            "max":      round(self.max_seen, 4),
        }

    def from_dict(self, d: dict) -> None:
        self.ema_efficiency = float(d.get("ema_eff", 0.96))
        self.sample_count   = int(d.get("samples", 0))
        self.classification = d.get("class", "learning")
        self.confidence     = float(d.get("conf", 0.0))
        self.min_seen       = float(d.get("min", 1.0))
        self.max_seen       = float(d.get("max", 0.0))


class InverterEfficiencyTracker:
    """
    Leert DC→AC rendement per omvormer.
    Identificeert rendementsproblemen vroeg.
    """

    def __init__(self, hass) -> None:
        self._hass   = hass
        self._store  = None
        self._state: Dict[str, InverterEffState] = {}
        self._dirty_count = 0
        self._hint_engine = None
        self._decisions_history = None

    def set_hint_engine(self, he) -> None:
        self._hint_engine = he

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY)
        data = await self._store.async_load()
        if data:
            for inv_id, d in data.items():
                self._state[inv_id] = InverterEffState()
                self._state[inv_id].from_dict(d)

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save(
                {k: v.to_dict() for k, v in self._state.items()}
            )
            self._dirty_count = 0

    def observe(
        self,
        inverter_id: str,
        dc_power_w: Optional[float],
        ac_power_w: Optional[float],
    ) -> Optional[float]:
        """
        Verwerk één meting. Geeft geleerd rendement terug (of None).
        dc_power_w: gemeten DC-input (van MPPT/string-sensor)
        ac_power_w: gemeten AC-output (grid-zijde van omvormer)
        """
        if dc_power_w is None or ac_power_w is None:
            return None
        if dc_power_w < MIN_DC_W:
            return None   # te weinig productie voor betrouwbare meting

        efficiency = ac_power_w / dc_power_w
        efficiency = max(0.0, min(1.5, efficiency))   # clamp outliers

        if inverter_id not in self._state:
            self._state[inverter_id] = InverterEffState()
        st = self._state[inverter_id]

        old_class = st.classification
        st.ema_efficiency = EMA_ALPHA * efficiency + (1 - EMA_ALPHA) * st.ema_efficiency
        st.sample_count   = min(st.sample_count + 1, 99999)
        st.min_seen       = min(st.min_seen, efficiency)
        st.max_seen       = max(st.max_seen, efficiency)
        self._dirty_count += 1

        if st.sample_count >= MIN_SAMPLES:
            self._classify(inverter_id, st)
            if st.classification != old_class:
                self._log(inverter_id, st)
                if st.classification not in ("ok", "learning"):
                    self._emit_hint(inverter_id, st, dc_power_w, ac_power_w)

        return round(st.ema_efficiency, 3)

    def _classify(self, inv_id: str, st: InverterEffState) -> None:
        eff = st.ema_efficiency
        if eff > EFF_MAX_NORMAL:
            st.classification = "sensor_error"   # AC > DC: onmogelijk
            st.confidence     = min(0.95, (eff - 1.0) * 10)
        elif eff < EFF_MIN_ALERT:
            st.classification = "poor_efficiency"
            st.confidence     = min(0.92, (EFF_MIN_NORMAL - eff) / EFF_MIN_NORMAL)
        elif eff < EFF_MIN_NORMAL:
            st.classification = "low_efficiency"
            st.confidence     = min(0.80, (EFF_MIN_NORMAL - eff) / 0.06)
        else:
            st.classification = "ok"
            st.confidence     = min(0.99, (eff - EFF_MIN_NORMAL) / (1.0 - EFF_MIN_NORMAL))

    def _emit_hint(
        self, inv_id: str, st: InverterEffState,
        dc_w: float, ac_w: float
    ) -> None:
        if not self._hint_engine:
            return
        messages = {
            "poor_efficiency": (
                f"Omvormer '{inv_id}' heeft een laag rendement van "
                f"{st.ema_efficiency*100:.1f}% (normaal 94–98%). "
                f"DC: {dc_w:.0f}W → AC: {ac_w:.0f}W. "
                f"Mogelijke oorzaken: degradatie, defect, of verkeerde sensor."
            ),
            "low_efficiency": (
                f"Omvormer '{inv_id}' rendement {st.ema_efficiency*100:.1f}% "
                f"is iets onder normaal (94–98%). Nog geen alarm, maar houd het in de gaten."
            ),
            "sensor_error": (
                f"Omvormer '{inv_id}': gemeten AC-vermogen ({ac_w:.0f}W) is groter dan DC "
                f"({dc_w:.0f}W) — dit is fysiek onmogelijk. Waarschijnlijk verkeerde sensor."
            ),
        }
        msg = messages.get(st.classification)
        if not msg:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"inverter_efficiency_{inv_id.replace('.', '_')}",
                title      = f"Omvormer rendement: {inv_id}",
                message    = msg,
                action     = f"Controleer DC-sensor van omvormer '{inv_id}'",
                confidence = st.confidence,
            )
        except Exception as _e:
            _LOGGER.debug("InverterEfficiency hint fout: %s", _e)

    def _log(self, inv_id: str, st: InverterEffState) -> None:
        _LOGGER.info(
            "InverterEfficiency [%s]: %s (eff=%.3f, n=%d)",
            inv_id, st.classification, st.ema_efficiency, st.sample_count,
        )
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "inverter_efficiency",
                    action   = st.classification,
                    reason   = inv_id,
                    message  = (
                        f"Omvormer {inv_id}: {st.classification} "
                        f"(rendement {st.ema_efficiency*100:.1f}%)"
                    ),
                    extra    = {
                        "inverter_id":  inv_id,
                        "ema_eff":      round(st.ema_efficiency, 4),
                        "samples":      st.sample_count,
                        "classification": st.classification,
                    },
                )
            except Exception:
                pass

    def get_diagnostics(self) -> dict:
        return {k: v.to_dict() for k, v in self._state.items()}
