# -*- coding: utf-8 -*-
"""
CloudEMS PowerCalc Engine -- v1.0.0

Berekent geschat vermogen per HA-entiteit zonder dat PowerCalc
geinstalleerd hoeft te worden. Identieke strategieen als PowerCalc:
  fixed   -- vast vermogen aan/uit + optionele states (climate modes)
  linear  -- lineair met helderheid (lampen, dimmers)
  lut     -- lookup-table bri x color_temp x hs_color -> watt
  wled    -- LED-strip controllers (brightness x max_power)

Copyright (c) 2025 CloudEMS -- https://cloudems.eu
"""
from __future__ import annotations
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


@dataclass
class LUTEntry:
    bri:        int
    color_temp: Optional[int] = None
    hue:        Optional[int] = None
    sat:        Optional[int] = None
    watt:       float = 0.0


@dataclass
class PowerProfile:
    manufacturer: str
    model:        str
    device_type:  str           # "light","switch","media_player","climate",...
    strategy:     str           # "fixed","linear","lut","wled"
    # fixed
    power_on_w:   float = 0.0
    standby_w:    float = 0.0
    states_power: Dict[str, float] = field(default_factory=dict)
    # linear
    min_watt:     float = 0.0
    max_watt:     float = 0.0
    gamma_curve:  float = 1.0
    calibrate:    List[Tuple[int, float]] = field(default_factory=list)
    # lut
    lut_entries:  List[LUTEntry] = field(default_factory=list)
    # meta
    aliases:      List[str] = field(default_factory=list)
    source:       str = "builtin"   # builtin | remote | powercalc_local

    @property
    def profile_key(self) -> str:
        return f"{self.manufacturer.lower()}/{self.model.lower()}"


class PowerCalcEngine:
    """Bereken actueel vermogen vanuit een PowerProfile + HA-state."""

    def calculate(self, profile: PowerProfile, state: str, attrs: Dict[str, Any]) -> float:
        if state in ("unavailable", "unknown"):
            return 0.0
        is_on = state not in ("off", "0", "false", "idle", "standby", "sleep")
        if not is_on:
            return profile.standby_w

        s = profile.strategy
        if s == "fixed":   return self._fixed(profile, state, attrs)
        if s == "linear":  return self._linear(profile, attrs)
        if s == "lut":     return self._lut(profile, attrs)
        if s == "wled":    return self._wled(profile, attrs)
        return profile.power_on_w

    def _fixed(self, p: PowerProfile, state: str, attrs: Dict) -> float:
        if p.states_power and state in p.states_power:
            return p.states_power[state]
        return p.power_on_w

    def _linear(self, p: PowerProfile, attrs: Dict) -> float:
        bri = float(attrs.get("brightness", 255))
        bri_pct = min(1.0, bri / 255.0)
        if p.gamma_curve != 1.0:
            bri_pct = math.pow(bri_pct, p.gamma_curve)
        if p.calibrate:
            return self._interpolate(bri, p.calibrate)
        return round(p.min_watt + bri_pct * (p.max_watt - p.min_watt), 2)

    def _lut(self, p: PowerProfile, attrs: Dict) -> float:
        if not p.lut_entries:
            return self._linear(p, attrs)
        bri        = int(attrs.get("brightness", 255))
        color_temp = attrs.get("color_temp")
        hs         = attrs.get("hs_color")
        best, best_dist = None, float("inf")
        for e in p.lut_entries:
            d = abs(e.bri - bri)
            if color_temp and e.color_temp:
                d += abs(e.color_temp - color_temp) * 0.5
            if hs and e.hue is not None:
                d += abs(e.hue - hs[0]) * 0.02
            if d < best_dist:
                best_dist, best = d, e
        return best.watt if best else 0.0

    def _wled(self, p: PowerProfile, attrs: Dict) -> float:
        bri = float(attrs.get("brightness", 255)) / 255.0
        return p.standby_w + bri * p.power_on_w

    @staticmethod
    def _interpolate(bri: float, points: List[Tuple[int, float]]) -> float:
        pts = sorted(points, key=lambda x: x[0])
        if bri <= pts[0][0]:  return pts[0][1]
        if bri >= pts[-1][0]: return pts[-1][1]
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]; x1, y1 = pts[i + 1]
            if x0 <= bri <= x1:
                t = (bri - x0) / max(x1 - x0, 1)
                return round(y0 + t * (y1 - y0), 2)
        return pts[-1][1]
