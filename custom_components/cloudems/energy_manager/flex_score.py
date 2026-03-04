"""
CloudEMS Flexibel Vermogen Score — v1.0.0

Berekent real-time hoeveel kW aan flexibele last er beschikbaar is
om te verschuiven of in te plannen.

Bronnen:
  • Batterij:     vrije capaciteit × max. laadstroom (indien niet vol)
  • EV:           aanwezig + max laadstroom × geschatte resterende sessietijd
  • Boiler:       schakelbaar vermogen als hij nu UIT staat en kan aan
  • NILM:         apparaten die verschoven kunnen worden (wasmachine, vaatwasser, droogkast)

Score wordt uitgesplitst naar categorie en als totaal sensor gepubliceerd.
Bruikbaar voor congestiemanagement, saldering-optimalisatie en diagnose.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# NILM device types die als "verschuifbaar" worden beschouwd
SHIFTABLE_DEVICE_TYPES = {
    "washing_machine", "dishwasher", "dryer", 
    "oven", "ev_charger",
}

# Geschatte piekvermogen per apparaattype (W) als NILM geen waarde heeft
DEVICE_POWER_DEFAULTS: dict[str, float] = {
    "washing_machine": 2000,
    "dishwasher":      1800,
    "dryer":           2400,
    "oven":            2000,
    "ev_charger":      7400,
}


@dataclass
class FlexComponent:
    """Één flexibiliteitsbron met label en vermogen."""
    source: str         # "battery" | "ev" | "boiler_<id>" | "nilm_<device>"
    label: str
    flex_kw: float      # Beschikbaar flexibel vermogen in kW
    reason: str         # Korte toelichting


@dataclass
class FlexScore:
    """Resultaat van de flexibiliteitscalculatie."""
    total_kw: float
    battery_kw: float
    ev_kw: float
    boiler_kw: float
    nilm_kw: float
    components: list[FlexComponent] = field(default_factory=list)
    breakdown: str = ""    # Mensleesbare samenvatting


def calculate_flex_score(
    *,
    # Batterij
    battery_soc_pct: Optional[float]  = None,    # State of Charge 0-100
    battery_capacity_kwh: Optional[float] = None, # Bruikbare capaciteit
    battery_max_charge_kw: Optional[float] = None,# Max laadvermogen
    # EV
    ev_connected: bool               = False,
    ev_max_charge_kw: float          = 0.0,
    ev_session_hours_remaining: float= 0.0,       # uren tot vertrek
    # Boilers / slimme stopcontacten
    boiler_status: list[dict]        = None,       # coordinator boiler_status
    # NILM apparaten
    nilm_devices: list[dict]         = None,       # coordinator nilm_devices
) -> FlexScore:
    """
    Bereken de totale flexibele vermogensscore.

    Parameters worden doorgegeven vanuit de coordinator.
    """
    components: list[FlexComponent] = []
    battery_kw = ev_kw = boiler_kw = nilm_kw = 0.0

    # ── Batterij ──────────────────────────────────────────────────────────────
    if battery_soc_pct is not None and battery_capacity_kwh and battery_max_charge_kw:
        free_pct    = max(0.0, 100.0 - battery_soc_pct)
        free_kwh    = free_pct / 100.0 * battery_capacity_kwh
        if free_kwh > 0.5:   # alleen als er zinvolle ruimte is
            kw = min(battery_max_charge_kw, free_kwh)   # begrensd door vermogen
            battery_kw = round(kw, 2)
            components.append(FlexComponent(
                source  = "battery",
                label   = "Batterij",
                flex_kw = battery_kw,
                reason  = f"{free_kwh:.1f} kWh vrij ({free_pct:.0f}%) @ max {battery_max_charge_kw:.1f} kW",
            ))

    # ── EV ────────────────────────────────────────────────────────────────────
    if ev_connected and ev_max_charge_kw > 0:
        # Flex is beschikbaar als de EV er staat en nog tijd heeft
        useful_h = min(ev_session_hours_remaining, 4.0)   # max 4 uur plannen
        kw       = ev_max_charge_kw if useful_h >= 0.5 else ev_max_charge_kw * 0.5
        ev_kw    = round(kw, 2)
        components.append(FlexComponent(
            source  = "ev",
            label   = "EV-lader",
            flex_kw = ev_kw,
            reason  = f"{ev_max_charge_kw:.1f} kW max, ~{useful_h:.0f}h sessie over",
        ))

    # ── Boilers / slimme stopcontacten ────────────────────────────────────────
    for boiler in (boiler_status or []):
        is_on    = boiler.get("is_on", False)
        power_w  = float(boiler.get("power_w", 0))
        label    = boiler.get("label", "Boiler")
        action   = boiler.get("action", "")
        # Flex = schakelbaar als apparaat nu uit is (kan aan bij behoefte)
        if not is_on and power_w > 0 and action != "congestion_off":
            kw = round(power_w / 1000, 2)
            boiler_kw += kw
            components.append(FlexComponent(
                source  = f"boiler_{boiler.get('entity_id','?')}",
                label   = label,
                flex_kw = kw,
                reason  = f"Momenteel UIT, schakelbaar ({power_w:.0f} W)",
            ))

    # ── NILM verschuifbare apparaten ──────────────────────────────────────────
    for dev in (nilm_devices or []):
        dtype = dev.get("device_type", "")
        is_on = dev.get("is_on", False)
        label = dev.get("name") or dev.get("label") or dtype
        pwr_w = float(dev.get("current_power") or DEVICE_POWER_DEFAULTS.get(dtype, 0))

        if dtype in SHIFTABLE_DEVICE_TYPES and not is_on and pwr_w > 0:
            kw = round(pwr_w / 1000, 2)
            nilm_kw += kw
            components.append(FlexComponent(
                source  = f"nilm_{dev.get('device_id', dtype)}",
                label   = label,
                flex_kw = kw,
                reason  = f"Verschuifbaar ({pwr_w:.0f} W), nu niet actief",
            ))

    total_kw = round(battery_kw + ev_kw + boiler_kw + nilm_kw, 2)

    # Mensleesbare samenvatting
    parts = []
    if battery_kw: parts.append(f"batterij {battery_kw:.1f} kW")
    if ev_kw:      parts.append(f"EV {ev_kw:.1f} kW")
    if boiler_kw:  parts.append(f"boiler {boiler_kw:.1f} kW")
    if nilm_kw:    parts.append(f"apparaten {nilm_kw:.1f} kW")
    breakdown = f"{total_kw:.1f} kW flex: " + (", ".join(parts) if parts else "geen flexibele last")

    return FlexScore(
        total_kw   = total_kw,
        battery_kw = battery_kw,
        ev_kw      = ev_kw,
        boiler_kw  = boiler_kw,
        nilm_kw    = nilm_kw,
        components = components,
        breakdown  = breakdown,
    )
