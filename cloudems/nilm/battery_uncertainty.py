# -*- coding: utf-8 -*-
"""
CloudEMS NILM BatteryUncertaintyTracker — v1.0.0

Beheert NILM-maskering voor thuisbatterijen met onbetrouwbare of vertraagde
metingen, zoals de Zonneplan Nexus (~60s updatevertraging).

Kernprobleem:
  De bestaande staleness-guard in coordinator.py doet EMA-decay als een
  batterij-entity ouder is dan 90s. Dit is verkeerd: een Nexus die 3 kW laadt
  en 60s geen update geeft, laadt waarschijnlijk nog steeds ~3 kW. Door te
  decayen naar 0 denkt NILM dat de batterij inactief is, en detecteert het
  de stroomfluctuaties van de omvormer als "warmtepomp" of "boiler".

Vier beschermingslagen:

LAAG 1 — Stale-breedte masker
  Als een battery-entity stale is (ouder dan STALE_THRESHOLD_S), wordt de
  NILM-maskeerbreedte verbreed tot de laatste bekende waarde ±STALE_MARGIN_W.
  Zo worden events die het gevolg zijn van batterij-ruis onderdrukt, ook al
  ontvangen we geen nieuwe meting.

LAAG 2 — Burst-update detectie
  Als na een stale periode ineens een grote vermogenssprong binnenkomt
  (bijv. 0→3200W omdat de Nexus 60s stil was), wordt een verlengd masker
  gezet (BURST_MASK_S). Alle NILM-events die ín de stale periode zijn
  aangemaakt en qua vermogen overeenkomen met de burst worden achteraf
  verwijderd.

LAAG 3 — Grid-delta estimatie
  Als geen batterijmeting beschikbaar is maar grid + solar wél gemeten worden,
  schatten we het batterijvermogen als:
    estimated_batt = grid_w + solar_w - house_baseline_w
  Hiermee kunnen we de ramp-bescherming actief houden ook zonder directe meting.

LAAG 4 — Provider-profielen
  Elke batterij-provider heeft een bekend onzekerheidsvenster:
    nexus:   90s updatevertraging, burst-updates
    local:   10s (directe HA-entity)
    cloud:   30-60s (API-gebaseerd)
  Het maskervenster wordt aangepast op het provider-profiel.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Provider-profielen ────────────────────────────────────────────────────────
PROVIDER_PROFILES: dict[str, dict] = {
    "nexus":    {"stale_s": 75,  "burst_mask_s": 120, "margin_w": 400},
    "zonneplan":{"stale_s": 75,  "burst_mask_s": 120, "margin_w": 400},
    "cloud":    {"stale_s": 45,  "burst_mask_s":  60, "margin_w": 250},
    "local":    {"stale_s": 25,  "burst_mask_s":  30, "margin_w": 150},
    "default":  {"stale_s": 60,  "burst_mask_s":  90, "margin_w": 300},
}

# ── Configuratie ──────────────────────────────────────────────────────────────
GRID_ESTIMATE_MARGIN_W  = 200.0  # W — onzekerheid in grid-delta schatting
MIN_BURST_DELTA_W       = 500.0  # W — minimale sprong om als burst te detecteren
STALE_MARGIN_W          = 350.0  # W — extra marge bij stale meting (default)


@dataclass
class BatteryState:
    """State van één geconfigureerde batterij."""
    label:          str
    provider:       str = "default"

    # Laatste bekende waarden
    last_power_w:   float = 0.0
    last_update_ts: float = field(default_factory=time.time)
    last_real_ts:   float = field(default_factory=time.time)  # echte meting (niet stale)

    # Schattingswaarde (grid-delta)
    estimated_w:    float = 0.0
    has_estimate:   bool  = False

    # Masker-state
    mask_until:     float = 0.0   # blokkeer NILM tot dit tijdstip
    mask_reason:    str   = ""

    @property
    def profile(self) -> dict:
        return PROVIDER_PROFILES.get(self.provider, PROVIDER_PROFILES["default"])

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_real_ts) > self.profile["stale_s"]

    @property
    def effective_power_w(self) -> float:
        """Beste schatting van huidig batterijvermogen."""
        if not self.is_stale:
            return self.last_power_w
        if self.has_estimate:
            return self.estimated_w
        # Stale zonder schatting: houd laatste waarde (niet decayen)
        return self.last_power_w

    @property
    def uncertainty_w(self) -> float:
        """Onzekerheidsbreedte rondom effective_power_w."""
        if not self.is_stale:
            return self.profile["margin_w"] * 0.5
        # Stale: onzekerheid groeit met tijd
        stale_s = time.time() - self.last_real_ts
        growth = min(3.0, stale_s / self.profile["stale_s"])
        return self.profile["margin_w"] * (1.0 + growth)

    @property
    def is_masked(self) -> bool:
        return time.time() < self.mask_until

    def set_mask(self, duration_s: float, reason: str) -> None:
        self.mask_until = time.time() + duration_s
        self.mask_reason = reason
        _LOGGER.debug(
            "BatteryUncertainty '%s': masker %.0fs — %s",
            self.label, duration_s, reason,
        )

    def update_real(self, power_w: float) -> tuple[bool, float]:
        """
        Verwerk een echte meting. Geeft (burst_detected, burst_delta_w).
        burst_detected=True als de meting een grote sprong vertoont t.o.v.
        de vorige waarde (wijst op een stale-periode met burst-update).
        """
        now = time.time()
        delta = abs(power_w - self.last_power_w)
        stale_before = self.is_stale  # was stale vóór deze update?

        self.last_power_w  = power_w
        self.last_real_ts  = now
        self.last_update_ts = now
        self.has_estimate  = False  # echte meting beschikbaar

        burst = stale_before and delta >= MIN_BURST_DELTA_W
        return burst, delta

    def update_estimate(self, grid_w: float, solar_w: float, baseline_w: float) -> None:
        """
        Schat batterijvermogen via grid-delta als geen echte meting beschikbaar.
        Formule: P_batt ≈ P_solar - P_grid - P_baseline
        (positief = laden, negatief = ontladen)
        """
        if not self.is_stale:
            return
        est = solar_w - grid_w - baseline_w
        # Alleen betrouwbaar als solar of grid significant zijn
        if abs(solar_w) > 100 or abs(grid_w) > 100:
            self.estimated_w = est
            self.has_estimate = True


class BatteryUncertaintyTracker:
    """
    Centrale NILM-bescherming voor traag/onbetrouwbaar gemeten batterijen.

    Gebruik vanuit NILMDetector:

        # Init:
        self._batt_uncertainty = BatteryUncertaintyTracker()

        # Registreer batterijen bij setup:
        self._batt_uncertainty.register("Nexus", provider="nexus")

        # Update elke cycle:
        burst, delta = self._batt_uncertainty.update("Nexus", power_w)
        if burst:
            self._nilm.set_extended_battery_mask(delta)

        # Vóór elk NILM-event:
        if self._batt_uncertainty.should_suppress_nilm(delta_w):
            return  # onderdrukt door batterij-onzekerheid

        # Achteraf opruimen na burst:
        self._batt_uncertainty.cleanup_burst_false_positives(devices, delta_w)
    """

    def __init__(self) -> None:
        self._batteries: dict[str, BatteryState] = {}
        self._unconfigured_suspected: bool = False
        self._unconfigured_mask_until: float = 0.0

    def register(self, label: str, provider: str = "default") -> None:
        """Registreer een bekende batterij."""
        if label not in self._batteries:
            self._batteries[label] = BatteryState(label=label, provider=provider)
            _LOGGER.debug(
                "BatteryUncertainty: '%s' geregistreerd (provider=%s, stale_s=%ds)",
                label, provider,
                PROVIDER_PROFILES.get(provider, PROVIDER_PROFILES["default"])["stale_s"],
            )

    def update(self, label: str, power_w: float) -> tuple[bool, float]:
        """
        Verwerk een batterijmeting. Geeft (burst_detected, burst_delta_w).
        Zet automatisch een burst-masker als een stale-periode eindigt met
        een grote vermogenssprong.
        """
        if label not in self._batteries:
            self.register(label)

        batt = self._batteries[label]
        burst, delta = batt.update_real(power_w)

        if burst:
            profile = batt.profile
            batt.set_mask(
                profile["burst_mask_s"],
                f"burst-update na stale periode (Δ{delta:.0f}W)",
            )
            _LOGGER.info(
                "BatteryUncertainty '%s': burst-update gedetecteerd Δ%.0fW "
                "— NILM geblokkeerd %.0fs",
                label, delta, profile["burst_mask_s"],
            )

        return burst, delta

    def update_estimate(self, label: str, grid_w: float,
                        solar_w: float, baseline_w: float) -> None:
        """Bijwerk grid-delta schatting voor een stale batterij."""
        if label in self._batteries:
            self._batteries[label].update_estimate(grid_w, solar_w, baseline_w)

    def flag_unconfigured_battery(self, duration_s: float = 60.0) -> None:
        """
        Stel in dat er waarschijnlijk een ongeconfigureerde batterij actief is.
        Wordt aangeroepen door de coordinator als grote onverklaarbare
        vermogensschommelingen worden gedetecteerd die niet door bekende
        bronnen verklaard worden.
        """
        self._unconfigured_suspected = True
        self._unconfigured_mask_until = time.time() + duration_s
        _LOGGER.debug(
            "BatteryUncertainty: ongeconfigureerde batterij vermoed "
            "— NILM geblokkeerd %.0fs", duration_s,
        )

    def should_suppress_nilm(
        self,
        delta_w: float,
        phase:   str = "L1",
    ) -> tuple[bool, str]:
        """
        Geeft (suppress, reden) voor een NILM-event.
        Controleert alle batterijen op actieve maskers en onzekerheidsvensters.
        """
        now = time.time()

        # Ongeconfigureerde batterij
        if self._unconfigured_suspected and now < self._unconfigured_mask_until:
            return True, "ongeconfigureerde batterij vermoed"

        abs_delta = abs(delta_w)

        for label, batt in self._batteries.items():
            # Actief masker (burst of stale)
            if batt.is_masked:
                return True, (
                    f"batterij '{label}' masker actief: {batt.mask_reason} "
                    f"(nog {batt.mask_until - now:.0f}s)"
                )

            # Onzekerheidsvenster: delta valt binnen eff_power ± uncertainty
            if batt.effective_power_w > 100:
                low  = batt.effective_power_w - batt.uncertainty_w
                high = batt.effective_power_w + batt.uncertainty_w
                if low <= abs_delta <= high:
                    source = "stale" if batt.is_stale else "actief"
                    return True, (
                        f"delta {abs_delta:.0f}W valt in onzekerheidsvenster "
                        f"batterij '{label}' "
                        f"({low:.0f}–{high:.0f}W, {source})"
                    )

        return False, ""

    def cleanup_burst_false_positives(
        self,
        devices: dict,
        burst_delta_w: float,
        label: str,
    ) -> list[str]:
        """
        Verwijder NILM-apparaten die waarschijnlijk door een burst-update zijn
        aangemaakt. Geeft lijst van verwijderde device_ids.

        Criteria voor verwijdering:
          - Apparaat is NIET bevestigd door gebruiker
          - Apparaat is aangemaakt ná de laatste echte meting van deze batterij
          - Vermogen valt binnen 40% van de burst-delta
        """
        if label not in self._batteries:
            return []

        batt = self._batteries[label]
        cutoff_ts = batt.last_real_ts  # aangemaakt ná laatste echte meting

        to_remove = []
        fp_types = {
            "heat_pump", "boiler", "electric_heater", "unknown",
            "air_source_heat_pump", "ground_source_heat_pump",
        }

        for did, dev in list(devices.items()):
            if did.startswith("__"):
                continue  # injected devices nooit verwijderen
            if getattr(dev, "confirmed", False):
                continue
            if getattr(dev, "user_feedback", "") == "correct":
                continue
            if getattr(dev, "device_type", "") not in fp_types:
                continue

            dev_w = getattr(dev, "current_power", 0) or getattr(dev, "nominal_power_w", 0)
            if dev_w < 50:
                continue

            ratio = dev_w / burst_delta_w if burst_delta_w > 0 else 0.0
            created = getattr(dev, "first_seen", 0) or getattr(dev, "last_seen", 0)

            if 0.35 <= ratio <= 1.65 and created >= cutoff_ts:
                to_remove.append(did)
                _LOGGER.info(
                    "BatteryUncertainty: verwijder burst-FP '%s' (%.0fW) "
                    "— batterij '%s' burst Δ%.0fW",
                    getattr(dev, "name", did), dev_w, label, burst_delta_w,
                )

        return to_remove

    def get_stats(self) -> dict:
        """Diagnose-statistieken voor dashboard."""
        now = time.time()
        return {
            "batteries": [
                {
                    "label":          b.label,
                    "provider":       b.provider,
                    "power_w":        round(b.last_power_w, 0),
                    "effective_w":    round(b.effective_power_w, 0),
                    "is_stale":       b.is_stale,
                    "stale_s":        round(now - b.last_real_ts, 0),
                    "uncertainty_w":  round(b.uncertainty_w, 0),
                    "is_masked":      b.is_masked,
                    "mask_remaining": round(max(0, b.mask_until - now), 0),
                    "mask_reason":    b.mask_reason,
                    "has_estimate":   b.has_estimate,
                    "estimated_w":    round(b.estimated_w, 0) if b.has_estimate else None,
                }
                for b in self._batteries.values()
            ],
            "unconfigured_suspected": self._unconfigured_suspected,
        }
