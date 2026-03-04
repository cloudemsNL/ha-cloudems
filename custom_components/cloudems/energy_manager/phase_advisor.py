"""
CloudEMS Fase-Migratie Adviseur — v1.0.0

Combineert drie databronnen om concrete fase-migratie-adviezen te geven:
  1. Fase-belasting (coordinator phase_data) — welke fase is zwaarst?
  2. Omvormer-fase (solar_learner)           — welke PV op welke fase?
  3. Apparaat-fase (NILM)                    — welke last op welke fase?

Logica:
  - Bereken structurele ongelijkheid over meerdere uren
  - Identificeer verplaatsbare apparaten op overbelaste fase
  - Identificeer lege fasen als bestemming
  - Bereken winst in balanspercentage bij verplaatsing

Output:
  sensor.cloudems_fase_advies → state = "Verplaats wasmachine van L1 naar L3 (+18% balans)"
  attributes: gedetailleerde breakdown

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Apparaattypen die fysiek verplaatsbaar zijn (stopcontact wisselen)
MOVABLE_DEVICE_TYPES = {
    "washing_machine", "dishwasher", "dryer",
    "refrigerator", "ev_charger",
}

# Minimale ongelijkheid om advies te geven (Ampère)
MIN_IMBALANCE_A = 3.0


@dataclass
class PhaseMigrationAdvice:
    """Eén specifiek migratie-advies."""
    device_label:       str
    device_type:        str
    from_phase:         str     # L1 / L2 / L3
    to_phase:           str
    current_load_w:     float   # apparaatbelasting in W
    balance_gain_pct:   float   # geschatte verbetering in balanspercentage
    explanation:        str


@dataclass
class PhaseMigrationReport:
    """Rapport van alle migratie-adviezen."""
    advices:            list[PhaseMigrationAdvice]
    overloaded_phase:   Optional[str]
    lightest_phase:     Optional[str]
    imbalance_a:        float
    summary:            str
    has_advice:         bool


def generate_migration_advice(
    *,
    phase_currents: dict[str, float],            # {"L1": 12.3, "L2": 5.1, "L3": 8.7}
    inverter_phases: dict[str, str],             # {inverter_id: "L1"} (from solar_learner)
    nilm_devices: list[dict],                    # coordinator nilm_devices
    voltage_v: float = 230.0,
) -> PhaseMigrationReport:
    """
    Genereer fase-migratie-adviezen.

    Parameters
    ----------
    phase_currents  : actuele fasestroom per fase (A)
    inverter_phases : bekende fase per omvormer (uit solar_learner)
    nilm_devices    : lijst van NILM-gedetecteerde apparaten
    voltage_v       : netspanning (default 230V)
    """
    if not phase_currents or len(phase_currents) < 2:
        return PhaseMigrationReport(
            advices=[], overloaded_phase=None, lightest_phase=None,
            imbalance_a=0.0, summary="Geen fase-data beschikbaar.", has_advice=False,
        )

    # Identificeer overbelaste en lichtste fase
    max_phase = max(phase_currents, key=phase_currents.get)
    min_phase = min(phase_currents, key=phase_currents.get)
    imbalance = phase_currents[max_phase] - phase_currents[min_phase]

    if imbalance < MIN_IMBALANCE_A:
        return PhaseMigrationReport(
            advices=[], overloaded_phase=max_phase, lightest_phase=min_phase,
            imbalance_a=round(imbalance, 2),
            summary=f"Fase-balans is goed (ongelijkheid {imbalance:.1f} A). Geen actie nodig.",
            has_advice=False,
        )

    advices: list[PhaseMigrationAdvice] = []

    # Zoek apparaten op de overbelaste fase die verplaatst kunnen worden
    for dev in nilm_devices:
        dtype       = dev.get("device_type", "")
        dev_phase   = dev.get("detected_phase") or dev.get("phase")
        label       = dev.get("name") or dev.get("label") or dtype
        power_w     = float(dev.get("current_power") or 0)

        if dtype not in MOVABLE_DEVICE_TYPES:
            continue
        if dev_phase != max_phase:
            continue
        if power_w < 100:
            continue

        # Bereken verbetering: hoeveel Ampère verschuift van max naar min fase?
        device_current_a = power_w / voltage_v
        new_max  = phase_currents[max_phase] - device_current_a
        new_min  = phase_currents[min_phase] + device_current_a
        new_imbalance = abs(new_max - new_min)
        improvement_pct = round((imbalance - new_imbalance) / imbalance * 100, 1) if imbalance > 0 else 0.0

        if improvement_pct < 5.0:
            continue   # Verwaarloosbare winst

        explanation = (
            f"'{label}' zit op {max_phase} (zwaarst belast: {phase_currents[max_phase]:.1f} A). "
            f"Verplaatsen naar {min_phase} ({phase_currents[min_phase]:.1f} A) verbetert de balans "
            f"met ~{improvement_pct:.0f}%."
        )

        advices.append(PhaseMigrationAdvice(
            device_label    = label,
            device_type     = dtype,
            from_phase      = max_phase,
            to_phase        = min_phase,
            current_load_w  = round(power_w),
            balance_gain_pct= improvement_pct,
            explanation     = explanation,
        ))

    # Sorteer op hoogste winst
    advices.sort(key=lambda a: a.balance_gain_pct, reverse=True)

    # Controleer ook of een omvormer op overbelaste fase staat
    inverter_notes = []
    for inv_id, inv_phase in inverter_phases.items():
        if inv_phase == max_phase:
            inverter_notes.append(
                f"Omvormer op {max_phase}: exporteert op de zwaarst belaste fase — "
                "overweeg faseverdeling bij volgende installatie."
            )

    if advices:
        top = advices[0]
        summary = (
            f"Fase {max_phase} is zwaarst belast ({phase_currents[max_phase]:.1f} A, "
            f"ongelijkheid {imbalance:.1f} A). "
            f"Aanbeveling: verplaats {top.device_label} van {top.from_phase} naar {top.to_phase} "
            f"(+{top.balance_gain_pct:.0f}% balansverbetering)."
        )
    else:
        summary = (
            f"Fase {max_phase} is het meest belast (ongelijkheid {imbalance:.1f} A), "
            "maar er zijn geen eenvoudig verplaatsbare apparaten geïdentificeerd. "
            + ("; ".join(inverter_notes) if inverter_notes else "")
        )

    return PhaseMigrationReport(
        advices         = advices,
        overloaded_phase= max_phase,
        lightest_phase  = min_phase,
        imbalance_a     = round(imbalance, 2),
        summary         = summary,
        has_advice      = bool(advices),
    )
