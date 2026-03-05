"""
CloudEMS Structurele Schaduwdetector — v1.0.0

Detecteert structurele schaduw op PV-panelen door per uur de werkelijke
opbrengst te vergelijken met de verwachte opbrengst (op basis van het
historisch geleerde opbrengstprofiel en de beschikbare irradiantie).

Hoe het werkt:
  • Elke 10 seconden ontvangt de detector de huidige opbrengst per omvormer.
  • Per uur wordt een "yield ratio" berekend: actual_frac / expected_frac.
    - expected_frac = geleerd historisch uurprofiel (hourly_yield_fraction
      uit pv_forecast), gecorrigeerd voor de huidige irradiantie.
    - actual_frac = current_w / peak_wp.
  • Per uur per omvormer wordt een exponentieel voortschrijdend gemiddelde
    (EMA) van de yield ratio bijgehouden.
  • Een uur met een structureel lage yield ratio (< SHADOW_THRESHOLD) over
    minimaal MIN_SHADOW_DAYS wordt als "beschaduwd" gelabeld.

Schaduwrichting:
  • Schaduw vroeg in de ochtend (07-10u) → waarschijnlijk oost-obstakel
    (boom, schoorsteen, gebouw ten oosten).
  • Schaduw laat in de middag (15-18u) → waarschijnlijk west-obstakel.
  • Schaduw rond zonnemiddag (11-14u) → hoog obstakel recht voor het paneel
    (bijv. schoorsteen), of grove vervuiling/beschadiging van de string.

Output per omvormer:
  • Lijst van beschaduwde uren met ernst (shadow_ratio)
  • Beschaduwingsrichting (oost / west / midden / onduidelijk)
  • Geschat dagelijks kWh-verlies door schaduw
  • Mensleesbaar advies

Opslag: HA Store (persistent over HA-herstarts).

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_shadow_detector_v1"
STORAGE_VERSION = 1
SAVE_INTERVAL_S = 600

# Een uur wordt als 'beschaduwd' gezien als de yield ratio structureel
# onder dit percentage van verwacht ligt.
SHADOW_THRESHOLD      = 0.72   # < 72% van verwacht = schaduw-kandidaat
PARTIAL_SHADOW_THRESH = 0.88   # 72-88% = gedeeltelijke schaduw

# Minimale dagen met data voordat een conclusie wordt getrokken
MIN_SHADOW_DAYS = 3   # sneller detecteren: 3 zonnige dagen volstaan

# Adaptive EMA alpha: snel bij weinig data, stabiel daarna
EMA_ALPHA_FAST = 0.25   # eerste 5 samples per uur-slot
EMA_ALPHA_MID  = 0.12   # samples 5-15
EMA_ALPHA_SLOW = 0.05   # daarna (stabiel, ≈ 20 meetdagen tijdconstante)

# Uren die tellen als 'ochtend', 'middag', 'namiddag' in lokale UTC-offset
# (voor NL/BE: UTC+1 winter, UTC+2 zomer — we werken in UTC, offset ~0-2)
MORNING_HOURS   = list(range(5, 10))    # 07-10u lokaal ≈ 05-10u UTC
MIDDAY_HOURS    = list(range(10, 14))   # 12-16u lokaal
AFTERNOON_HOURS = list(range(14, 19))   # 16-21u lokaal

# Minimale waarde voor een betrouwbare meting (om nacht-ruis te vermijden)
MIN_EXPECTED_FRAC = 0.05   # verwacht minstens 5% van piekopbrengst


@dataclass
class HourShadowProfile:
    """Schaduwprofiel voor één uur van de dag per omvormer."""
    hour: int                      # 0-23 UTC
    yield_ratio_ema: float = 1.0   # EMA van actual/expected (1.0 = perfect)
    samples: int           = 0     # Aantal relevante meetdagen

    @property
    def is_shadowed(self) -> bool:
        return self.samples >= MIN_SHADOW_DAYS and self.yield_ratio_ema < SHADOW_THRESHOLD

    @property
    def is_partial(self) -> bool:
        return (self.samples >= MIN_SHADOW_DAYS
                and SHADOW_THRESHOLD <= self.yield_ratio_ema < PARTIAL_SHADOW_THRESH)

    def to_dict(self) -> dict:
        return {
            "hour":            self.hour,
            "yield_ratio_ema": round(self.yield_ratio_ema, 4),
            "samples":         self.samples,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HourShadowProfile":
        return cls(
            hour            = int(d.get("hour", 0)),
            yield_ratio_ema = float(d.get("yield_ratio_ema", 1.0)),
            samples         = int(d.get("samples", 0)),
        )


@dataclass
class InverterShadowResult:
    """Schaduwanalyse voor één omvormer."""
    inverter_id:    str
    label:          str
    shadowed_hours: list[int]         # uren (UTC) met structurele schaduw
    partial_hours:  list[int]         # uren met gedeeltelijke schaduw
    direction:      str               # "oost" | "west" | "midden" | "multi" | "geen"
    severity:       str               # "ernstig" | "matig" | "licht" | "geen"
    lost_kwh_day_est: float           # geschat dagelijks verlies (kWh)
    advice:         str
    hour_profiles:  list[dict]        # alle uurprofielen voor debug/dashboard


@dataclass
class ShadowDetectionResult:
    """Totaalresultaat voor alle omvormers."""
    inverters:          list[InverterShadowResult]
    any_shadow:         bool
    total_lost_kwh_day: float
    summary:            str


class ShadowDetector:
    """
    Detecteert structurele schaduw per omvormer op basis van
    uurlijkse yield-ratio analyse.

    Gebruik vanuit coordinator:
        detector.tick(inverter_id, label, current_w, peak_wp,
                      expected_frac, hour_utc)
        result = detector.get_result()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass   = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # inverter_id → {hour → HourShadowProfile}
        self._profiles: dict[str, dict[int, HourShadowProfile]] = {}
        self._labels:   dict[str, str] = {}
        self._peak_wp:  dict[str, float] = {}

        # Per-inverter per-hour: track if we already updated this hour today
        # to avoid double-counting within the same hour
        self._last_update_hour: dict[str, int] = {}

        self._dirty      = False
        self._last_save  = 0.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for inv_id, hours_data in saved.items():
            self._profiles[inv_id] = {}
            for h_str, h_data in hours_data.items():
                try:
                    h = int(h_str)
                    self._profiles[inv_id][h] = HourShadowProfile.from_dict(h_data)
                except Exception:
                    pass
        _LOGGER.info(
            "CloudEMS ShadowDetector: geladen voor %d omvormers", len(self._profiles)
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            data = {}
            for inv_id, hours in self._profiles.items():
                data[inv_id] = {
                    str(h): prof.to_dict() for h, prof in hours.items()
                }
            await self._store.async_save(data)
            self._dirty     = False
            self._last_save = time.time()

    def tick(
        self,
        inverter_id:   str,
        label:         str,
        current_w:     float,
        peak_wp:       float,
        expected_frac: float,   # verwacht fractie van piek (0-1), uit pv_forecast
        hour_utc:      int,     # huidig UTC-uur (0-23)
    ) -> None:
        """
        Verwerk één meting. Wordt elke 10s aangeroepen vanuit de coordinator.

        Doet alleen een EMA-update als:
          1. expected_frac > MIN_EXPECTED_FRAC (zinnige uren, geen nacht)
          2. peak_wp > 50 W (omvormer is geconfigureerd)
          3. We dit uur nog niet bijgewerkt hebben (1 update per uur per omvormer)
        """
        try:
            self._labels[inverter_id] = label
            self._peak_wp[inverter_id] = max(self._peak_wp.get(inverter_id, 0.0), peak_wp)

            if peak_wp < 50 or expected_frac < MIN_EXPECTED_FRAC:
                return

            # Eén EMA-update per uur per omvormer (niet elk tick)
            last_h = self._last_update_hour.get(inverter_id, -1)
            if last_h == hour_utc:
                return
            self._last_update_hour[inverter_id] = hour_utc

            actual_frac = current_w / peak_wp if peak_wp > 0 else 0.0
            ratio       = min(actual_frac / expected_frac, 1.5)  # cap op 1.5

            profiles = self._profiles.setdefault(inverter_id, {})
            if hour_utc not in profiles:
                profiles[hour_utc] = HourShadowProfile(hour=hour_utc, yield_ratio_ema=ratio)
            else:
                p = profiles[hour_utc]
                n = p.samples
                ema_a = EMA_ALPHA_FAST if n < 5 else (EMA_ALPHA_MID if n < 15 else EMA_ALPHA_SLOW)
                p.yield_ratio_ema = p.yield_ratio_ema * (1 - ema_a) + ratio * ema_a

            profiles[hour_utc].samples += 1
            total_samples = sum(p.samples for p in profiles.values())
            trained_hours = sum(1 for p in profiles.values() if p.samples >= MIN_SHADOW_DAYS)
            _LOGGER.debug(
                "ShadowDetector '%s': uur %02d:00 sample %d — yield_ratio=%.2f | "
                "%d uren getraind, %d metingen totaal",
                label, hour_utc, profiles[hour_utc].samples, ratio,
                trained_hours, total_samples,
            )
            self._dirty = True

        except Exception as exc:
            _LOGGER.warning("ShadowDetector.tick error voor %s: %s", inverter_id, exc)

    def get_result(self) -> ShadowDetectionResult:
        """Bereken en retourneer het schaduwrapport voor alle omvormers."""
        try:
            results: list[InverterShadowResult] = []

            for inv_id, hours in self._profiles.items():
                label   = self._labels.get(inv_id, inv_id[-8:])
                peak_wp = self._peak_wp.get(inv_id, 0.0)

                shadowed = [h for h, p in hours.items() if p.is_shadowed]
                partial  = [h for h, p in hours.items() if p.is_partial]

                direction = self._detect_direction(shadowed + partial)
                severity  = self._classify_severity(shadowed, partial)

                # Schat dagelijks verlies:
                # Verlies per uur = (1 - ratio) × expected_frac × peak_wp / 1000
                # We approximeren expected_frac als 0.5 voor middag-uren als we
                # geen betere info hebben (conservatieve schatting).
                lost_kwh = 0.0
                for h, p in hours.items():
                    if p.is_shadowed or p.is_partial:
                        # Typisch uurprofiel: sinusvorm, piek ~0.8 rond zon-middag
                        # Ruwe benadering: expected_frac ≈ sin(π*(h-6)/12) * 0.7 (overdag)
                        import math
                        h_solar = (h - 6) % 24
                        exp_approx = max(0.0, math.sin(math.pi * h_solar / 12) * 0.7)
                        loss_frac  = max(0.0, 1.0 - p.yield_ratio_ema) * exp_approx
                        lost_kwh  += loss_frac * peak_wp / 1000.0
                lost_kwh = round(lost_kwh, 2)

                advice = self._build_advice(label, shadowed, partial, direction, lost_kwh)

                results.append(InverterShadowResult(
                    inverter_id     = inv_id,
                    label           = label,
                    shadowed_hours  = sorted(shadowed),
                    partial_hours   = sorted(partial),
                    direction       = direction,
                    severity        = severity,
                    lost_kwh_day_est= lost_kwh,
                    advice          = advice,
                    hour_profiles   = [
                        p.to_dict() for h, p in sorted(hours.items())
                        if p.samples >= 2
                    ],
                ))

            any_shadow = any(
                bool(r.shadowed_hours or r.partial_hours) for r in results
            )
            total_lost = round(sum(r.lost_kwh_day_est for r in results), 2)

            summary = self._build_summary(results, total_lost)

            return ShadowDetectionResult(
                inverters          = results,
                any_shadow         = any_shadow,
                total_lost_kwh_day = total_lost,
                summary            = summary,
            )
        except Exception as exc:
            _LOGGER.warning("ShadowDetector.get_result error: %s", exc)
            return ShadowDetectionResult(
                inverters=[], any_shadow=False, total_lost_kwh_day=0.0,
                summary="Schaduwdetectie tijdelijk niet beschikbaar."
            )

    @staticmethod
    def _detect_direction(affected_hours: list[int]) -> str:
        """Bepaal de waarschijnlijke schaduwrichting op basis van de getroffen uren."""
        if not affected_hours:
            return "geen"
        morning   = sum(1 for h in affected_hours if h in MORNING_HOURS)
        midday    = sum(1 for h in affected_hours if h in MIDDAY_HOURS)
        afternoon = sum(1 for h in affected_hours if h in AFTERNOON_HOURS)
        total     = len(affected_hours)

        if total == 0:
            return "geen"
        if morning / total >= 0.6:
            return "oost"
        if afternoon / total >= 0.6:
            return "west"
        if midday / total >= 0.5:
            return "midden"
        return "multi"

    @staticmethod
    def _classify_severity(shadowed: list, partial: list) -> str:
        total = len(shadowed) + len(partial)
        if total == 0:
            return "geen"
        if len(shadowed) >= 3:
            return "ernstig"
        if len(shadowed) >= 1 or len(partial) >= 3:
            return "matig"
        return "licht"

    @staticmethod
    def _build_advice(
        label: str,
        shadowed: list[int],
        partial: list[int],
        direction: str,
        lost_kwh: float,
    ) -> str:
        if not shadowed and not partial:
            return f"{label}: geen structurele schaduw gedetecteerd."

        direction_nl = {
            "oost":   "oostelijk obstakel (boom, gebouw, schoorsteen aan de oostkant)",
            "west":   "westelijk obstakel (boom, gebouw, schoorsteen aan de westkant)",
            "midden": "obstakel recht voor de panelen (hoge schoorsteen, antenne) of vervuiling",
            "multi":  "meerdere obstakels of complexe schaduwpatroon",
            "geen":   "onbekende richting",
        }.get(direction, "onbekende richting")

        uren_str = ", ".join(f"{h}:00" for h in sorted(shadowed + partial))
        verlies  = f"~{lost_kwh:.1f} kWh/dag" if lost_kwh > 0.1 else "beperkt verlies"

        if shadowed:
            return (
                f"{label}: structurele schaduw op uren {uren_str} UTC. "
                f"Waarschijnlijk {direction_nl}. "
                f"Geschat verlies: {verlies}. "
                f"Overweeg snoei, verplaatsing paneel, of bypass-diode controle."
            )
        return (
            f"{label}: gedeeltelijke schaduw op uren {uren_str} UTC. "
            f"Mogelijke oorzaak: {direction_nl}. "
            f"Geschat verlies: {verlies}."
        )

    @staticmethod
    def _build_summary(results: list[InverterShadowResult], total_lost: float) -> str:
        if not results:
            return "Onvoldoende data voor schaduwanalyse."

        shadowed_invs = [r for r in results if r.shadowed_hours or r.partial_hours]
        if not shadowed_invs:
            return "Geen structurele schaduw gedetecteerd op de geconfigureerde omvormers."

        labels = ", ".join(r.label for r in shadowed_invs)
        return (
            f"Schaduw gedetecteerd bij: {labels}. "
            f"Geschat totaal verlies: ~{total_lost:.1f} kWh/dag."
        )
