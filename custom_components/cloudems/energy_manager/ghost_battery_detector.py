"""
CloudEMS Ghost Battery Detector — v1.0.0

Detecteert thuisbatterijen en omvormers die niet geconfigureerd zijn via
vermogenspatroon-analyse. Houdt een virtuele SoC bij als geen API beschikbaar is.

Wat wordt gedetecteerd:
  - Thuisbatterij: grote bidirectionele vermogensstappen zonder inrush,
    gecorreleerd met solar/grid patroon, CV-fase zichtbaar bij hoge SoC
  - Onbekende omvormer/PV: onverklaard productievermogen op een fase,
    volgend op zonnecurve

Garanties:
  - Raakt geconfigureerde batterijen en sensoren NIET aan
  - Produceert alleen waarschuwingen en virtuele attributen
  - Geen schrijfacties naar echte actuatoren
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Drempelwaarden ────────────────────────────────────────────────────────────
BATTERY_MIN_STEP_W      = 400.0   # minimale vermogensstap om als batterij-kandidaat te tellen
BATTERY_MAX_STEP_W      = 8000.0  # maximale redelijke thuisbatterij
BATTERY_BIDIRECTIONAL_N = 3       # aantal bidirectionele events voor detectie-bevestiging
BATTERY_SOLAR_CORR_MIN  = 0.55    # minimale correlatie met solar om als batterij te tellen
VIRTUAL_SOC_CAPACITY_KWH = 10.0   # geschatte capaciteit als onbekend (wordt geleerd)
VIRTUAL_SOC_MIN_PCT      = 2.0
VIRTUAL_SOC_MAX_PCT      = 98.0

INVERTER_MIN_W           = 200.0  # minimaal onverklaard productievermogen
INVERTER_SOLAR_CORR_MIN  = 0.70   # hogere correlatie vereist voor omvormer-detectie

OBSERVATION_WINDOW_S     = 3600   # 1 uur observatievenster voor patroonherkenning
CONFIRM_AFTER_EVENTS     = 5      # events voor waarschuwing


@dataclass
class PowerEvent:
    ts:       float
    delta_w:  float   # positief = plotselinge stijging, negatief = daling
    phase:    str
    solar_w:  float
    grid_w:   float


@dataclass
class GhostBattery:
    """Gedetecteerde maar niet-geconfigureerde batterij."""
    first_seen:       float = field(default_factory=time.time)
    last_seen:        float = field(default_factory=time.time)
    charge_events:    int   = 0
    discharge_events: int   = 0
    estimated_power_w: float = 0.0    # huidig geschat vermogen (+ = laden, - = ontladen)
    virtual_soc_pct:  float = 50.0    # geschatte SoC
    capacity_kwh:     float = VIRTUAL_SOC_CAPACITY_KWH
    confirmed:        bool  = False
    phase:            str   = "?"
    peak_charge_w:    float = 0.0
    peak_discharge_w: float = 0.0

    def update_soc(self, power_w: float, dt_h: float) -> None:
        """Integreer vermogen in virtuele SoC."""
        delta_pct = (power_w * dt_h / (self.capacity_kwh * 1000)) * 100.0
        self.virtual_soc_pct = max(VIRTUAL_SOC_MIN_PCT,
                                   min(VIRTUAL_SOC_MAX_PCT, self.virtual_soc_pct + delta_pct))
        # Leer capaciteit bij: als SoC 100% bereikt terwijl we nog laden,
        # was de capaciteit groter dan geschat
        if self.virtual_soc_pct >= VIRTUAL_SOC_MAX_PCT and power_w > 100:
            self.capacity_kwh = min(self.capacity_kwh * 1.05, 20.0)
        elif self.virtual_soc_pct <= VIRTUAL_SOC_MIN_PCT and power_w < -100:
            self.capacity_kwh = min(self.capacity_kwh * 1.05, 20.0)


# Drempel voor automatische correctie (strenger dan detectie)
AUTO_CORRECT_CONFIDENCE_MIN = 0.68   # 68% confidence voor auto-correctie (4 goede dagen = ~72%)
AUTO_CORRECT_MIN_DAYS       = 2      # minimaal 2 dagen observatie
AUTO_CORRECT_MIN_OBS        = 50     # minimaal 50 daglicht-observaties


@dataclass
class GhostInverter:
    """Gedetecteerde maar niet-geconfigureerde omvormer/PV."""
    first_seen:        float = field(default_factory=time.time)
    last_seen:         float = field(default_factory=time.time)
    peak_w:            float = 0.0
    current_w:         float = 0.0
    phase:             str   = "?"
    confirmed:         bool  = False
    auto_correcting:   bool  = False   # True = vermogen wordt al opgeteld bij solar
    solar_corr_sum:    float = 0.0
    solar_corr_n:      int   = 0
    # Stabiliteit: bijhouden of patroon consistent is over meerdere dagen
    daily_peaks:       list  = field(default_factory=list)   # piek per dag (max 7)
    last_day:          int   = -1   # dag-index voor dagelijkse piek-tracking

    @property
    def solar_correlation(self) -> float:
        if self.solar_corr_n == 0:
            return 0.0
        return self.solar_corr_sum / self.solar_corr_n

    @property
    def confidence(self) -> float:
        """Gecombineerde confidence: correlatie × stabiliteit × observaties."""
        if self.solar_corr_n < 5:
            return 0.0
        corr_score  = self.solar_correlation                          # 0-1
        obs_score   = min(1.0, self.solar_corr_n / AUTO_CORRECT_MIN_OBS)  # 0-1
        # Stabiliteit: zijn de dagelijkse pieken consistent?
        stab_score  = 0.5
        if len(self.daily_peaks) >= 2:
            avg = sum(self.daily_peaks) / len(self.daily_peaks)
            if avg > 0:
                variance_pct = (max(self.daily_peaks) - min(self.daily_peaks)) / avg
                stab_score = max(0.0, 1.0 - variance_pct)
        return round(corr_score * 0.5 + obs_score * 0.3 + stab_score * 0.2, 3)

    @property
    def ready_for_auto_correct(self) -> bool:
        """True als confidence hoog genoeg is voor automatische correctie."""
        return (
            self.confirmed and
            self.confidence >= AUTO_CORRECT_CONFIDENCE_MIN and
            self.solar_corr_n >= AUTO_CORRECT_MIN_OBS and
            len(self.daily_peaks) >= AUTO_CORRECT_MIN_DAYS
        )


class GhostBatteryDetector:
    """
    Detecteert onbekende batterijen en omvormers via vermogenspatronen.

    Gebruik:
        detector = GhostBatteryDetector(configured_battery_eids)
        detector.observe(solar_w, grid_w, house_w, phase_w, dt_s)
        alerts = detector.get_alerts()
    """

    def __init__(self, configured_battery_power_w: float = 0.0) -> None:
        self._configured_bat_w  = configured_battery_power_w
        self._ghost_battery:    Optional[GhostBattery]  = None
        self._ghost_inverter:   Optional[GhostInverter] = None
        self._events:           list[PowerEvent] = []
        self._prev_ts:          float = 0.0
        self._prev_grid_w:      float = 0.0
        self._prev_solar_w:     float = 0.0
        self._prev_unexplained: float = 0.0
        self._last_alert_ts:    float = 0.0   # throttle waarschuwingen

    def update_configured_battery(self, power_w: float) -> None:
        """Bijwerken van het geconfigureerde batterijvermogen (voor aftrek)."""
        self._configured_bat_w = power_w

    def observe(self,
                solar_w:   float,
                grid_w:    float,
                house_w:   float,
                battery_w: float,
                dt_s:      float,
                phase:     str = "?") -> None:
        """
        Verwerk één tick meetdata.

        solar_w:   gemeten PV (positief)
        grid_w:    netto grid (positief = import, negatief = export)
        house_w:   gemeten huisverbruik
        battery_w: geconfigureerde batterij vermogen (positief = laden)
        dt_s:      tijd sinds vorige observatie
        """
        if dt_s <= 0 or dt_s > 3600:  # max 1 uur gap (bijv. HA offline geweest)
            self._prev_ts = time.time()
            return

        now = time.time()
        dt_h = dt_s / 3600.0

        # ── Kirchhoff: wat is onverklaard? ────────────────────────────────────
        # Verwacht: solar - grid - battery - house = 0
        # Onverklaard = afwijking die niet door bekende bronnen verklaard wordt
        kirchhoff_residual = solar_w - grid_w - battery_w - house_w

        # ── Detectie 1: Ghost Battery ─────────────────────────────────────────
        self._detect_battery(solar_w, grid_w, battery_w, kirchhoff_residual,
                              dt_h, phase, now)

        # ── Detectie 2: Ghost Inverter (onbekende PV) ─────────────────────────
        self._detect_inverter(solar_w, grid_w, battery_w, house_w, kirchhoff_residual,
                               dt_h, phase, now)

        # ── Deactivatie: als onverklaard vermogen verdwenen is → reset ────────
        # Gebruiker heeft de omvormer/accu geconfigureerd → residual daalt naar 0
        self._check_deactivation(solar_w, grid_w, battery_w, house_w, now)

        # ── Virtuele SoC bijwerken ────────────────────────────────────────────
        if self._ghost_battery and self._ghost_battery.confirmed:
            self._ghost_battery.update_soc(
                self._ghost_battery.estimated_power_w, dt_h
            )

        self._prev_grid_w  = grid_w
        self._prev_solar_w = solar_w
        self._prev_ts      = now

    def _detect_battery(self, solar_w: float, grid_w: float, battery_w: float,
                        residual: float, dt_h: float, phase: str, now: float) -> None:
        """
        Detecteer onbekende batterij via bidirectionele vermogensstappen
        gecorreleerd met solar/grid.
        """
        grid_delta = grid_w - self._prev_grid_w

        # Grote snelle grid-sprong gecombineerd met solar = mogelijk batterij
        # Batterij ladt → grid daalt (minder import of meer export)
        # Batterij ontlaadt → grid stijgt (meer import of minder export)
        if abs(grid_delta) < BATTERY_MIN_STEP_W:
            return
        if abs(grid_delta) > BATTERY_MAX_STEP_W:
            return

        # Check of solar actief is (correlatie vereist)
        if solar_w < 100.0 and grid_w > -200.0:
            return  # 's nachts zonder export — waarschijnlijk gewoon een load

        # Check of dit al verklaard wordt door geconfigureerde batterij
        if abs(battery_w) > 200 and abs(abs(battery_w) - abs(grid_delta)) < 300:
            return  # geconfigureerde batterij verklaart de sprong

        # Bidirectioneel patroon bijhouden
        if self._ghost_battery is None:
            self._ghost_battery = GhostBattery(phase=phase)

        gb = self._ghost_battery
        gb.last_seen = now

        if grid_delta < -BATTERY_MIN_STEP_W:
            # Grid daalt plotseling = iets begint energie te absorberen = laden
            gb.charge_events += 1
            gb.estimated_power_w = abs(grid_delta)
            gb.peak_charge_w = max(gb.peak_charge_w, abs(grid_delta))
        elif grid_delta > BATTERY_MIN_STEP_W:
            # Grid stijgt plotseling = iets begint energie te leveren = ontladen
            gb.discharge_events += 1
            gb.estimated_power_w = -abs(grid_delta)
            gb.peak_discharge_w = max(gb.peak_discharge_w, abs(grid_delta))

        total_events = gb.charge_events + gb.discharge_events
        if (not gb.confirmed and
                gb.charge_events >= 2 and gb.discharge_events >= 2 and
                total_events >= CONFIRM_AFTER_EVENTS):
            gb.confirmed = True
            _LOGGER.warning(
                "CloudEMS: Onbekende batterij gedetecteerd! "
                "Laad-events=%d, ontlaad-events=%d, geschat vermogen=%.0fW. "
                "Configureer via CloudEMS → Verbruik & Comfort → Batterij.",
                gb.charge_events, gb.discharge_events, gb.peak_charge_w,
            )

    def _detect_inverter(self, solar_w: float, grid_w: float, battery_w: float,
                         house_w: float, residual: float, dt_h: float, phase: str, now: float) -> None:
        """
        Detecteer onbekende omvormer via onverklaard productievermogen.

        Formule: als export + huis meer is dan bekende solar + batterij-ontlading,
        moet er een onbekende productie-bron zijn.

        export + house = solar_known + battery_discharge + ghost_production
        ghost = (export + house) - solar - battery_discharge
              = (-grid + house) - solar - max(0, -battery)
        """
        if grid_w >= 0:
            return  # alleen detecteren bij export

        export_w = -grid_w
        # Gebruik house_trend als beschikbaar, anders schat minimaal 200W
        house_est = max(200.0, residual + solar_w + battery_w)
        # Eenvoudiger: netto onverklaard = export + huis_min - solar - batterij_ontlading
        battery_discharge = max(0.0, -battery_w)
        # Gebruik werkelijk huisverbruik ipv vaste 200W schatting
        unexplained_production = export_w + house_w - solar_w - battery_discharge

        if unexplained_production < INVERTER_MIN_W:
            return  # export volledig verklaard door bekende bronnen

        # Dag-check: alleen detecteren als er ook bekende solar actief is
        # Robuuster dan uurcheck — werkt ook bij hoge breedtegraden en zomertijd
        if solar_w < 100.0:
            return  # geen solar actief — onverklaard export 's nachts = batterij, geen PV

        # Correlatie met bekende solar: als solar ook hoog is, sterke correlatie
        solar_ratio = solar_w / max(unexplained_production, 1.0)
        corr_sample = min(1.0, solar_ratio) if solar_w > 50 else 0.0

        if self._ghost_inverter is None:
            self._ghost_inverter = GhostInverter(phase=phase)

        gi = self._ghost_inverter
        gi.last_seen   = now
        gi.current_w   = unexplained_production
        gi.peak_w      = max(gi.peak_w, unexplained_production)
        gi.solar_corr_sum += corr_sample
        gi.solar_corr_n   += 1

        # Dagelijkse piek bijhouden voor stabiliteitscore
        today = int(now / 86400)
        if today != gi.last_day:
            if gi.current_w > INVERTER_MIN_W:
                gi.daily_peaks.append(gi.current_w)
                if len(gi.daily_peaks) > 7:
                    gi.daily_peaks.pop(0)
            gi.last_day = today

        if (not gi.confirmed and
                gi.solar_corr_n >= 20 and
                gi.solar_correlation >= INVERTER_SOLAR_CORR_MIN and
                gi.peak_w >= INVERTER_MIN_W * 2):
            gi.confirmed = True
            _LOGGER.warning(
                "CloudEMS: Onbekende omvormer/PV gedetecteerd! "
                "Piek=%.0fW, solar-correlatie=%.0f%%, confidence=%.0f%%. "
                "Configureer via CloudEMS → Zonne-energie → Omvormer toevoegen.",
                gi.peak_w, gi.solar_correlation * 100, gi.confidence * 100,
            )

        # Auto-correctie activeren als confidence hoog genoeg
        if gi.confirmed and not gi.auto_correcting and gi.ready_for_auto_correct:
            gi.auto_correcting = True
            _LOGGER.warning(
                "CloudEMS: Virtuele omvormer actief — %.0fW opgeteld bij solar "
                "(confidence=%.0f%%, %d observaties, %d dagen). "
                "Configureer de omvormer om deze melding te verwijderen.",
                gi.current_w, gi.confidence * 100,
                gi.solar_corr_n, len(gi.daily_peaks),
            )

    def get_alerts(self) -> list[dict]:
        """Geeft actieve detectie-waarschuwingen terug."""
        alerts = []
        if self._ghost_battery and self._ghost_battery.confirmed:
            alerts.append({
                "type":     "ghost_battery",
                "message":  "Batterij gedetecteerd maar niet geconfigureerd",
                "detail":   f"Geschat vermogen: {abs(self._ghost_battery.estimated_power_w):.0f}W, "
                            f"virtuele SoC: {self._ghost_battery.virtual_soc_pct:.0f}%",
                "severity": "warning",
                "virtual_soc_pct":   round(self._ghost_battery.virtual_soc_pct, 1),
                "estimated_power_w": round(self._ghost_battery.estimated_power_w, 1),
                "peak_charge_w":     round(self._ghost_battery.peak_charge_w, 1),
                "peak_discharge_w":  round(self._ghost_battery.peak_discharge_w, 1),
            })
        if self._ghost_inverter and self._ghost_inverter.confirmed:
            alerts.append({
                "type":     "ghost_inverter",
                "message":  "Onbekende omvormer/PV gedetecteerd",
                "detail":   f"Piek: {self._ghost_inverter.peak_w:.0f}W, "
                            f"solar-correlatie: {self._ghost_inverter.solar_correlation*100:.0f}%",
                "severity": "warning",
                "peak_w":         round(self._ghost_inverter.peak_w, 1),
                "current_w":      round(self._ghost_inverter.current_w, 1),
                "solar_corr_pct": round(self._ghost_inverter.solar_correlation * 100, 1),
            })
        return alerts

    # Deactivatie tellers
    _deact_inverter_ticks: int = 0
    _deact_battery_ticks:  int = 0
    _DEACT_TICKS_NEEDED:   int = 3   # 3 opeenvolgende ticks zonder residual → deactiveer

    def _check_deactivation(self, solar_w: float, grid_w: float,
                             battery_w: float, house_w: float, now: float) -> None:
        """
        Controleer of de ghost devices gedeactiveerd moeten worden.
        Triggered als de gebruiker het apparaat heeft geconfigureerd:
        het onverklaarde vermogen verdwijnt dan uit het residual.
        """
        # Ghost inverter deactivatie
        gi = self._ghost_inverter
        if gi and gi.confirmed:
            export_w = max(0.0, -grid_w)
            battery_discharge = max(0.0, -battery_w)
            unexplained = export_w + house_w - solar_w - battery_discharge if grid_w < 0 else 0.0
            # Alleen deactiveren bij significante export (> 300W)
            # Bij lage solar (zonsopgang/-ondergang) of import: geen conclusie trekken
            if grid_w < -300 and solar_w > 200:
                if unexplained < INVERTER_MIN_W:
                    self._deact_inverter_ticks += 1
                else:
                    self._deact_inverter_ticks = 0

            if self._deact_inverter_ticks >= self._DEACT_TICKS_NEEDED:
                _was_auto = gi.auto_correcting
                self._ghost_inverter = None
                self._deact_inverter_ticks = 0
                _LOGGER.info(
                    "CloudEMS: Virtuele omvormer gedeactiveerd — "
                    "onverklaard vermogen verdwenen (omvormer geconfigureerd?). "
                    "Auto-correctie was: %s", _was_auto,
                )

        # Ghost battery deactivatie
        gb = self._ghost_battery
        if gb and gb.confirmed:
            grid_delta = abs(grid_w - self._prev_grid_w)
            if grid_delta < BATTERY_MIN_STEP_W / 2:
                self._deact_battery_ticks += 1
            else:
                self._deact_battery_ticks = 0

            # Ook deactiveren als geconfigureerde batterij nu het vermogen verklaart
            if abs(battery_w) > 200 and abs(abs(battery_w) - abs(gb.estimated_power_w)) < 500:
                self._deact_battery_ticks += self._DEACT_TICKS_NEEDED  # direct

            if self._deact_battery_ticks >= self._DEACT_TICKS_NEEDED * 5:  # battery conservatiever
                self._ghost_battery = None
                self._deact_battery_ticks = 0
                _LOGGER.info(
                    "CloudEMS: Virtuele batterij gedeactiveerd — "
                    "patroon verdwenen (batterij geconfigureerd?)."
                )

    def get_virtual_solar_w(self) -> float:
        """
        Geeft het virtuele omvormer-vermogen terug als auto-correctie actief is.
        Dit wordt opgeteld bij solar_power in de coordinator.
        Retourneert 0.0 als confidence onvoldoende is.
        """
        gi = self._ghost_inverter
        if gi and gi.auto_correcting and gi.current_w > 0:
            return gi.current_w
        return 0.0

    def get_status(self) -> dict:
        """Diagnostics voor dashboard."""
        gb = self._ghost_battery
        gi = self._ghost_inverter
        return {
            "ghost_battery": {
                "detected":          gb.confirmed if gb else False,
                "charge_events":     gb.charge_events if gb else 0,
                "discharge_events":  gb.discharge_events if gb else 0,
                "virtual_soc_pct":   round(gb.virtual_soc_pct, 1) if gb else None,
                "estimated_power_w": round(gb.estimated_power_w, 1) if gb else None,
                "capacity_kwh":      round(gb.capacity_kwh, 1) if gb else None,
            },
            "ghost_inverter": {
                "detected":      gi.confirmed if gi else False,
                "peak_w":        round(gi.peak_w, 1) if gi else None,
                "current_w":     round(gi.current_w, 1) if gi else None,
                "solar_corr":    round(gi.solar_correlation * 100, 1) if gi else None,
                "observations":  gi.solar_corr_n if gi else 0,
            },
        }
