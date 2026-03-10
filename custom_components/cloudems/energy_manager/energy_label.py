# -*- coding: utf-8 -*-
"""
CloudEMS Energie-label Simulator — v1.0.0

Schat het energielabel van het huis op basis van gemeten data:
  • W/K verliescoëfficiënt (uit ThermalHouseModel)
  • Jaarlijks gasverbruik (m³/jaar, uit GasAnalysis)
  • Jaarlijks elektriciteitsverbruik (kWh/jaar, uit BillSimulator)
  • PV-opbrengst (kWh/jaar, uit SolarLearner)
  • Woonoppervlak (m², uit config flow — optioneel)

Methode:
  Stap 1 — Primair energieverbruik (PEV) in kWh/m²/jaar:
    PEV = (gas_m3 × 9.77 kWh/m³ × 1.05 primair) + (elek_kWh × 2.56 primair) - (pv_kWh × 2.56)
    Gecorrigeerd voor vloeroppervlak als bekend.

  Stap 2 — Label o.b.v. NEN 7120 / RVO-klassengrenzen (NL, 2023):
    A++++ < 0     kWh/m²/jaar   (energiepositief)
    A+++  < 50
    A++   < 75
    A+    < 105
    A     < 160
    B     < 190
    C     < 250
    D     < 290
    E     < 335
    F     < 380
    G     ≥ 380

  Stap 3 — Vergelijk met nationaal gemiddelde (NL 2022: D, ~280 kWh/m²/jaar)

Stap 1 kan ook gebruikt worden zonder vloeroppervlak door W/K als proxy:
  Geschat oppervlak = W/K × 6.0 (empirische factor NL rij- en twee-onder-een-kapwoning)

Nota: dit is een benadering — geen officieel EPA-certificaat.

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# NEN 7120 / RVO labelgrenzen (kWh/m²/jaar primair)
LABEL_THRESHOLDS: list[tuple[str, float]] = [
    ("A++++",   0.0),
    ("A+++",   50.0),
    ("A++",    75.0),
    ("A+",    105.0),
    ("A",     160.0),
    ("B",     190.0),
    ("C",     250.0),
    ("D",     290.0),
    ("E",     335.0),
    ("F",     380.0),
    ("G",     float("inf")),
]

# Primaire energiefactoren (NEN 7120 / ISSO 82)
PEF_GAS   = 1.05    # aardgas incl. primaire energie voor winning/transport
PEF_ELEK  = 2.56    # elektriciteit (NL netspaningmix 2022)
PEF_PV    = 2.56    # PV vermijdt netspaningmix
GAS_KWH_PER_M3 = 9.77   # Groningengas calorische waarde

# Empirische W/K → m² factor (NL tussenwoningen, NEN 8088)
W_PER_K_TO_M2 = 6.0

# NL gemiddeld (RVO 2022)
NL_AVG_KWH_M2 = 280.0
NL_AVG_LABEL  = "D"


def _pev_to_label(pev_kwh_m2: float) -> str:
    """Zet PEV (kWh/m²/jaar) om naar energielabel."""
    for label, threshold in LABEL_THRESHOLDS:
        if pev_kwh_m2 < threshold:
            return label
    return "G"


@dataclass
class EnergyLabelResult:
    """Resultaat van de energie-label simulatie."""
    label:              str       # A++++ … G
    pev_kwh_m2:         float     # Primair energieverbruik per m²
    floor_area_m2:      float     # Gebruikt vloeroppervlak (gemeten of geschat)
    area_source:        str       # "configured" | "estimated_from_w_per_k"
    gas_kwh_year:       float     # Gasverbruik omgezet naar kWh
    electric_kwh_year:  float     # Netto elektriciteitsverbruik kWh
    pv_kwh_year:        float     # PV-opbrengst kWh
    nl_avg_label:       str = NL_AVG_LABEL
    nl_avg_pev:         float = NL_AVG_KWH_M2
    delta_vs_nl_avg:    float = 0.0   # pev − nl_avg (positief = slechter dan gemiddelde)
    reliable:           bool = False   # voldoende data
    advice:             str = ""


class EnergyLabelSimulator:
    """
    Schat het energielabel op basis van meetdata uit CloudEMS.

    Gebruik:
        sim = EnergyLabelSimulator()
        result = sim.calculate(
            w_per_k=185.0,
            gas_m3_year=1200.0,
            electric_kwh_year=3200.0,
            pv_kwh_year=2800.0,
            floor_area_m2=None,   # geschat uit W/K als None
        )
    """

    def calculate(
        self,
        w_per_k: float,
        gas_m3_year: float,
        electric_kwh_year: float,
        pv_kwh_year: float = 0.0,
        floor_area_m2: Optional[float] = None,
    ) -> EnergyLabelResult:
        """
        w_per_k           — ThermalHouseModel.w_per_k (0.0 = onbekend)
        gas_m3_year       — GasAnalysis geschat jaarverbruik (0.0 = geen gas / onbekend)
        electric_kwh_year — BillSimulator jaarverbruik import (netto)
        pv_kwh_year       — SolarLearner jaarproductie (0.0 = geen PV)
        floor_area_m2     — Uit config flow (None = schat)
        """
        reliable = True
        warnings = []

        # Vloeroppervlak
        if floor_area_m2 and floor_area_m2 > 20:
            area        = floor_area_m2
            area_source = "configured"
        elif w_per_k > 10:
            area        = round(w_per_k * W_PER_K_TO_M2, 0)
            area_source = "estimated_from_w_per_k"
            warnings.append("Vloeroppervlak geschat uit W/K-coëfficiënt")
        else:
            area        = 100.0   # NL gemiddeld
            area_source = "default_100m2"
            reliable    = False
            warnings.append("Geen vloeroppervlak of W/K beschikbaar — standaard 100m² gebruikt")

        if electric_kwh_year < 100:
            reliable = False
            warnings.append("Onvoldoende elektriciteitsmeting")

        # Primair energieverbruik
        gas_kwh    = gas_m3_year * GAS_KWH_PER_M3
        pev_gas    = gas_kwh * PEF_GAS
        pev_elek   = electric_kwh_year * PEF_ELEK
        pev_pv     = pv_kwh_year * PEF_PV     # vermeden primaire energie
        pev_total  = pev_gas + pev_elek - pev_pv
        pev_m2     = round(pev_total / area, 1)

        label      = _pev_to_label(pev_m2)
        delta      = round(pev_m2 - NL_AVG_KWH_M2, 1)

        advice = self._build_advice(label, pev_m2, delta, warnings, reliable)

        return EnergyLabelResult(
            label             = label,
            pev_kwh_m2        = pev_m2,
            floor_area_m2     = area,
            area_source       = area_source,
            gas_kwh_year      = round(gas_kwh, 0),
            electric_kwh_year = round(electric_kwh_year, 0),
            pv_kwh_year       = round(pv_kwh_year, 0),
            nl_avg_label      = NL_AVG_LABEL,
            nl_avg_pev        = NL_AVG_KWH_M2,
            delta_vs_nl_avg   = delta,
            reliable          = reliable,
            advice            = advice,
        )

    def _build_advice(
        self,
        label: str,
        pev: float,
        delta: float,
        warnings: list[str],
        reliable: bool,
    ) -> str:
        parts = []
        if not reliable:
            parts.append(f"⚠️ Schatting ({'; '.join(warnings)}).")
        if label in ("A++++", "A+++", "A++", "A+", "A"):
            parts.append(
                f"Jouw huis heeft label {label} "
                f"({pev:.0f} kWh/m²/jaar) — goed boven het NL gemiddelde."
            )
        elif label in ("B", "C"):
            parts.append(
                f"Label {label} ({pev:.0f} kWh/m²/jaar) — "
                f"iets boven het NL gemiddelde ({NL_AVG_KWH_M2:.0f} kWh/m²/jaar)."
            )
        else:
            parts.append(
                f"Label {label} ({pev:.0f} kWh/m²/jaar) — "
                f"{abs(delta):.0f} kWh/m² boven het NL gemiddelde. "
                f"Isolatie en/of warmtepomp kunnen dit verbeteren."
            )
        return " ".join(parts)

    def to_sensor_dict(self, result: EnergyLabelResult) -> dict:
        return {
            "label":              result.label,
            "pev_kwh_m2":         result.pev_kwh_m2,
            "floor_area_m2":      result.floor_area_m2,
            "area_source":        result.area_source,
            "gas_kwh_year":       result.gas_kwh_year,
            "electric_kwh_year":  result.electric_kwh_year,
            "pv_kwh_year":        result.pv_kwh_year,
            "nl_avg_label":       result.nl_avg_label,
            "nl_avg_pev_kwh_m2":  result.nl_avg_pev,
            "delta_vs_nl_avg":    result.delta_vs_nl_avg,
            "reliable":           result.reliable,
            "advice":             result.advice,
        }
