# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
phase_power_consistency.py — v4.6.531

Monitort of L1 + L2 + L3 consistent is met het totale grid-vermogen.

Kirchhoff per fase: sum(L1..L3) ≈ grid_total
Afwijkingen duiden op:
  - CT-klem op verkeerde fase of omgewisseld
  - Fase-sensor heeft verkeerd teken
  - Één fase niet geconfigureerd (mist)
  - Schaalfout op één fase

Zelflerend: EMA van afwijking per fase.
Zelfcorrigerend: offset-correctie bij hoog vertrouwen.
Meldingen via hint_engine.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_phase_consistency_v1"
STORAGE_VERSION = 1

EMA_ALPHA         = 0.08
MIN_SAMPLES       = 40
CORRECTION_CONF   = 0.80
SAVE_INTERVAL     = 60
OK_FRAC           = 0.05   # <5% afwijking = ok
WARN_FRAC         = 0.15   # >15% = waarschuwing
ALERT_FRAC        = 0.30   # >30% = alert


@dataclass
class PhaseConsistencyState:
    ema_residual:   float = 0.0
    ema_rel_dev:    float = 0.0
    sample_count:   int   = 0
    classification: str   = "learning"
    confidence:     float = 0.0
    corr_offset:    float = 0.0
    corrections:    int   = 0

    def to_dict(self) -> dict:
        return {
            "ema_res": round(self.ema_residual, 2),
            "ema_rel": round(self.ema_rel_dev, 4),
            "samples": self.sample_count,
            "class":   self.classification,
            "conf":    round(self.confidence, 4),
            "offset":  round(self.corr_offset, 2),
            "corrections": self.corrections,
        }

    def from_dict(self, d: dict) -> None:
        self.ema_residual   = float(d.get("ema_res", 0.0))
        self.ema_rel_dev    = float(d.get("ema_rel", 0.0))
        self.sample_count   = int(d.get("samples", 0))
        self.classification = d.get("class", "learning")
        self.confidence     = float(d.get("conf", 0.0))
        self.corr_offset    = float(d.get("offset", 0.0))
        self.corrections    = int(d.get("corrections", 0))


class PhasePowerConsistencyMonitor:
    """
    Controleert of L1+L2+L3 consistent is met totaal grid.
    Leert per-fase afwijkingen en corrigeert offsets.
    """

    PHASES = ["L1", "L2", "L3"]

    def __init__(self, hass) -> None:
        self._hass   = hass
        self._store  = None
        self._state: Dict[str, PhaseConsistencyState] = {
            ph: PhaseConsistencyState() for ph in self.PHASES
        }
        self._dirty_count   = 0
        self._hint_engine   = None
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
            for ph in self.PHASES:
                if ph in data:
                    self._state[ph].from_dict(data[ph])

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save(
                {ph: self._state[ph].to_dict() for ph in self.PHASES}
            )
            self._dirty_count = 0

    def observe(
        self,
        grid_total_w: Optional[float],
        l1_w: Optional[float],
        l2_w: Optional[float],
        l3_w: Optional[float],
    ) -> dict:
        """
        Verwerk één meetmoment.
        Geeft gecorrigeerde fase-vermogens terug.
        """
        if grid_total_w is None or abs(grid_total_w) < 50:
            return {"L1": l1_w, "L2": l2_w, "L3": l3_w}

        phase_vals = {"L1": l1_w, "L2": l2_w, "L3": l3_w}
        available  = {ph: v for ph, v in phase_vals.items() if v is not None}
        if len(available) < 2:
            return {"L1": l1_w, "L2": l2_w, "L3": l3_w}

        # Som van geconfigureerde fasen
        phase_sum = sum(available.values())
        # Als niet alle 3 beschikbaar: schaal het totaal naar het bekende aandeel
        if len(available) < 3:
            fraction = len(available) / 3.0
            expected_sum = grid_total_w * fraction
        else:
            expected_sum = grid_total_w

        total_residual = phase_sum - expected_sum
        per_phase_res  = total_residual / len(available)

        corrected = {}
        for ph in self.PHASES:
            val = phase_vals[ph]
            if val is None:
                corrected[ph] = None
                continue

            st = self._state[ph]
            res = val - (expected_sum / max(len(available), 1))
            # Gebruik het per-fase-residueel tov verwachte gelijke verdeling
            # als ruwe benadering — verfijn met geleerd offset
            actual_res = val + st.corr_offset - (grid_total_w / 3.0)

            st.ema_residual = EMA_ALPHA * actual_res + (1 - EMA_ALPHA) * st.ema_residual
            rel_dev = abs(actual_res) / max(abs(grid_total_w), 50.0)
            st.ema_rel_dev  = EMA_ALPHA * rel_dev + (1 - EMA_ALPHA) * st.ema_rel_dev
            st.sample_count = min(st.sample_count + 1, 99999)
            self._dirty_count += 1

            if st.sample_count >= MIN_SAMPLES:
                self._classify(ph, st, grid_total_w)

            # v4.6.545: geen correctie toepassen — pass-through
            corrected[ph] = val

        return corrected

    def _classify(self, ph: str, st: PhaseConsistencyState, total_w: float) -> None:
        rel = st.ema_rel_dev
        old = st.classification

        if rel < OK_FRAC:
            st.classification = "ok"
            st.confidence     = min(0.99, 1.0 - rel / OK_FRAC)
        elif rel < WARN_FRAC:
            st.classification = "minor_offset"
            st.confidence     = min(0.80, rel / WARN_FRAC * 0.8)
        elif rel < ALERT_FRAC:
            st.classification = "offset"
            st.confidence     = min(0.90, 0.6 + (rel - WARN_FRAC) / ALERT_FRAC)
            # v4.6.545: correctie uitgeschakeld — alleen observeren en melden
        else:
            st.classification = "major_deviation"
            st.confidence     = min(0.95, 0.7 + (rel - ALERT_FRAC))

        if st.classification != old:
            self._log(ph, f"classificatie_{old}_naar_{st.classification}",
                      f"rel_dev={rel:.3f} ema_res={st.ema_residual:.1f}W")
            if st.classification in ("offset", "major_deviation"):
                self._emit_hint(ph, st, total_w)

    def _emit_hint(self, ph: str, st: PhaseConsistencyState, total_w: float) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"phase_consistency_{ph.lower()}",
                title      = f"Fase {ph} afwijking gedetecteerd",
                message    = (
                    f"Fase {ph} wijkt structureel {st.ema_rel_dev*100:.0f}% af van "
                    f"het verwachte aandeel in het totale gridvermogen ({total_w:.0f}W). "
                    f"Mogelijke oorzaken: CT-klem op verkeerde fase, verkeerd teken, "
                    f"of schaalfout. "
                    f"{'Automatische offset-correctie toegepast.' if st.corrections > 0 else ''}"
                ),
                action     = f"Controleer fase {ph} sensor configuratie",
                confidence = st.confidence,
            )
        except Exception as _e:
            _LOGGER.debug("PhasePowerConsistency hint fout: %s", _e)

    def _log(self, ph: str, action: str, detail: str) -> None:
        _LOGGER.info("PhasePowerConsistency [%s]: %s — %s", ph, action, detail)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "phase_consistency",
                    action   = action,
                    reason   = ph,
                    message  = f"Fase {ph}: {action} — {detail}",
                    extra    = {"phase": ph, "detail": detail},
                )
            except Exception:
                pass

    def get_diagnostics(self) -> dict:
        return {ph: self._state[ph].to_dict() for ph in self.PHASES}
