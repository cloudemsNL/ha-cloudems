"""
CloudEMS House Consumption Learner — v1.0.0

Leert het werkelijke huisverbruik per uur (7×24 matrix, weekdag vs weekend).
Voorspelt:
  - Verwacht verbruik rest van vandaag (kWh)
  - Verwacht totaal vandaag (kWh)
  - Uren off-grid bij huidige batterij + PV

Gebruikt EMA per uurslot zodat seizoen en gedragswijzigingen automatisch
worden opgepikt zonder historische data te wissen.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Configuratie ─────────────────────────────────────────────────────────────
EMA_ALPHA_FAST  = 0.20   # eerste 10 observaties: snel leren
EMA_ALPHA_SLOW  = 0.05   # daarna: traag, stabiel
MIN_SAMPLES_RELIABLE = 7  # min. observaties per uurslot voor betrouwbare waarde
SLOT_MIN_W      = 10.0   # onder 10W negeren (sensor noise)
SLOT_MAX_W      = 20_000.0  # boven 20kW negeren (data fout)


@dataclass
class HourSlot:
    """Eén uurslot in de leermatrix."""
    ema_w:    float = 0.0    # EMA gemiddelde vermogen (W)
    samples:  int   = 0      # aantal observaties
    last_ts:  float = 0.0    # laatste update timestamp


class HouseConsumptionLearner:
    """
    Leert huisverbruik per uurslot (weekdag/weekend × 24 uur).

    Gebruik:
        learner = HouseConsumptionLearner()
        learner.observe(house_w=850.0)   # elke coordinator tick
        forecast = learner.forecast_today()
    """

    def __init__(self, hass=None) -> None:
        # [weekday_0_6][hour_0_23] — 0=maandag, 6=zondag
        self._slots: list[list[HourSlot]] = [
            [HourSlot() for _ in range(24)]
            for _ in range(7)
        ]
        self._last_hour: int  = -1
        self._hour_acc_w: list[float] = []   # accumuleer binnen het uur
        self._hass = hass
        self._store = None
        self._dirty = False       # True als er nieuwe data is die opgeslagen moet worden
        self._last_save_ts: float = 0.0
        if hass is not None:
            from homeassistant.helpers.storage import Store
            self._store = Store(hass, 1, "cloudems_house_consumption_learner_v1")

    def _now_slot(self) -> tuple[int, int]:
        """Geeft (weekday, hour) voor het huidige moment."""
        now = datetime.now()
        return now.weekday(), now.hour

    def observe(self, house_w: float) -> None:
        """
        Verwerk één vermogensmeting van het huis.
        Aanroepen elke coordinator tick (~1s).
        """
        if house_w < SLOT_MIN_W or house_w > SLOT_MAX_W:
            return

        weekday, hour = self._now_slot()

        # Nieuw uur → commit vorig uur naar EMA
        if hour != self._last_hour and self._last_hour >= 0 and self._hour_acc_w:
            avg_w = sum(self._hour_acc_w) / len(self._hour_acc_w)
            self._commit(self._last_hour, weekday, avg_w)
            self._hour_acc_w = []

        self._last_hour = hour
        self._hour_acc_w.append(house_w)

    def _commit(self, hour: int, weekday: int, avg_w: float) -> None:
        """Schrijf uurgemiddelde naar EMA slot."""
        slot = self._slots[weekday][hour]
        n = slot.samples
        alpha = EMA_ALPHA_FAST if n < 10 else EMA_ALPHA_SLOW
        slot.ema_w   = avg_w if n == 0 else slot.ema_w * (1 - alpha) + avg_w * alpha
        slot.samples = min(n + 1, 9999)
        slot.last_ts = time.time()
        self._dirty  = True

    async def async_load(self) -> None:
        """Laad geleerd model van HA Store na herstart."""
        if not self._store:
            return
        try:
            saved = await self._store.async_load()
            if not saved or "slots" not in saved:
                return
            for wd in range(7):
                for h in range(24):
                    s = saved["slots"][wd][h]
                    if s.get("samples", 0) >= 1:
                        self._slots[wd][h].ema_w   = float(s.get("ema_w", 0))
                        self._slots[wd][h].samples = int(s.get("samples", 0))
                        self._slots[wd][h].last_ts = float(s.get("last_ts", 0))
            self._dirty = False
            _LOGGER.debug("HouseConsumptionLearner: model geladen (%d slots actief)",
                          sum(self._slots[wd][h].samples > 0 for wd in range(7) for h in range(24)))
        except Exception as e:
            _LOGGER.debug("HouseConsumptionLearner load fout: %s", e)

    async def async_maybe_save(self) -> None:
        """Sla model op als er nieuwe data is (max 1x per uur)."""
        if not self._store or not self._dirty:
            return
        if time.time() - self._last_save_ts < 3600:
            return
        await self.async_save()

    async def async_save(self) -> None:
        """Sla huidig model op naar HA Store."""
        if not self._store:
            return
        try:
            data = {"slots": [
                [{"ema_w": round(self._slots[wd][h].ema_w, 1),
                  "samples": self._slots[wd][h].samples,
                  "last_ts": round(self._slots[wd][h].last_ts, 0)}
                 for h in range(24)]
                for wd in range(7)
            ]}
            await self._store.async_save(data)
            self._dirty = False
            self._last_save_ts = time.time()
            _LOGGER.debug("HouseConsumptionLearner: model opgeslagen")
        except Exception as e:
            _LOGGER.debug("HouseConsumptionLearner save fout: %s", e)

    def expected_w(self, weekday: int, hour: int) -> Optional[float]:
        """Geleerd verwacht vermogen voor dit uurslot (W)."""
        slot = self._slots[weekday][hour]
        if slot.samples < MIN_SAMPLES_RELIABLE:
            return None
        return round(slot.ema_w, 1)

    def forecast_today(self) -> dict:
        """
        Voorspelt verbruik voor de rest van vandaag en het totaal.

        Returns dict met:
          remaining_kwh   — verwacht kWh rest van vandaag
          total_kwh       — verwacht totaal vandaag (geleerd patroon)
          consumed_kwh    — al verbruikt vandaag (schatting)
          confidence      — 0-1, gebaseerd op aantal gevulde slots
          hourly_w        — lijst van 24 verwachte W-waarden
        """
        now          = datetime.now()
        weekday      = now.weekday()
        current_hour = now.hour
        current_min  = now.minute

        hourly_w: list[Optional[float]] = []
        for h in range(24):
            hourly_w.append(self.expected_w(weekday, h))

        # Gevulde slots tellen
        filled = sum(1 for w in hourly_w if w is not None)
        confidence = min(1.0, filled / 24)

        # Schat ontbrekende slots via globaal gemiddelde
        known = [w for w in hourly_w if w is not None]
        fallback_w = sum(known) / len(known) if known else 500.0

        hourly_filled = [w if w is not None else fallback_w for w in hourly_w]

        # Al verbruikt vandaag: uren 0..current_hour
        consumed_kwh = 0.0
        for h in range(current_hour):
            consumed_kwh += hourly_filled[h] / 1000.0  # W → kWh per uur

        # Huidig uur gedeeltelijk
        frac = current_min / 60.0
        consumed_kwh += hourly_filled[current_hour] / 1000.0 * frac

        # Rest van vandaag: current_hour..23
        remaining_kwh = 0.0
        remaining_frac = 1.0 - frac
        remaining_kwh += hourly_filled[current_hour] / 1000.0 * remaining_frac
        for h in range(current_hour + 1, 24):
            remaining_kwh += hourly_filled[h] / 1000.0

        total_kwh = consumed_kwh + remaining_kwh

        return {
            "remaining_kwh":  round(remaining_kwh, 2),
            "total_kwh":      round(total_kwh, 2),
            "consumed_kwh":   round(consumed_kwh, 2),
            "confidence":     round(confidence, 2),
            "hourly_w":       [round(w, 0) for w in hourly_filled],
            "current_hour_w": round(hourly_filled[current_hour], 0),
        }

    def survival_hours(self,
                       bat_kwh:      float,
                       pv_remain_kwh: float,
                       house_w_now:  Optional[float] = None) -> dict:
        """
        Berekent hoe lang het huis kan draaien op batterij + resterende PV.

        Gebruikt het geleerde verbruikspatroon per uur (veel beter dan een
        statisch getal — 's nachts verbruikt het huis minder dan overdag).

        Returns dict met:
          hours           — totaal te overbruggen uren
          until_time      — tijdstip waarop energie op is
          bat_depletes_h  — uren tot batterij leeg
          method          — "learned" of "current_w" of "fallback"
          detail          — lijst van uren met verwacht verbruik
        """
        now         = datetime.now()
        weekday     = now.weekday()
        hour        = now.hour
        minute      = now.minute
        frac        = minute / 60.0

        available_kwh = bat_kwh + pv_remain_kwh
        detail: list[dict] = []
        hours_survived = 0.0
        kwh_left = available_kwh
        bat_left = bat_kwh
        bat_depletes_h = None
        method = "learned"

        # Loop per uur vanaf nu
        for offset in range(48):   # max 48 uur vooruitkijken
            h = (hour + offset) % 24
            wd = (weekday + (hour + offset) // 24) % 7

            slot = self._slots[wd][h]
            if slot.samples >= MIN_SAMPLES_RELIABLE:
                expected = slot.ema_w
            elif house_w_now is not None and offset == 0:
                expected = house_w_now
                method = "current_w"
            else:
                expected = 500.0  # fallback
                if method == "learned":
                    method = "fallback"

            # Eerste uur gedeeltelijk
            duration = (1.0 - frac) if offset == 0 else 1.0
            needed_kwh = expected / 1000.0 * duration

            if kwh_left >= needed_kwh:
                kwh_left -= needed_kwh
                if bat_left > 0:
                    bat_left = max(0, bat_left - needed_kwh)
                    if bat_left == 0 and bat_depletes_h is None:
                        bat_depletes_h = hours_survived + (needed_kwh - max(0, needed_kwh - bat_kwh)) / (expected/1000.0) * duration
                hours_survived += duration
                detail.append({"hour": h, "expected_w": round(expected), "ok": True})
            else:
                # Gedeeltelijk uur overgebleven
                if expected > 0:
                    hours_survived += kwh_left / (expected / 1000.0)
                detail.append({"hour": h, "expected_w": round(expected), "ok": False})
                break

        # Bereken eindtijdstip
        end_ts = time.time() + hours_survived * 3600
        end_dt = datetime.fromtimestamp(end_ts)

        return {
            "hours":          round(hours_survived, 1),
            "until_time":     end_dt.strftime("%H:%M") if hours_survived < 48 else "48u+",
            "until_weekday":  ["ma","di","wo","do","vr","za","zo"][end_dt.weekday()],
            "bat_depletes_h": round(bat_depletes_h, 1) if bat_depletes_h else None,
            "available_kwh":  round(available_kwh, 2),
            "method":         method,
            "confidence":     round(min(1.0, sum(1 for d in detail[:24] if d["ok"]) / max(1, len(detail[:24]))), 2),
            "detail":         detail[:24],
        }

    def to_dict(self) -> dict:
        """Geeft status-dict terug voor sensor attribuut."""
        now = datetime.now()
        wd, h = now.weekday(), now.hour
        current = self.expected_w(wd, h)
        filled = sum(
            1 for day in self._slots
            for slot in day
            if slot.samples >= MIN_SAMPLES_RELIABLE
        )
        return {
            "current_hour_expected_w": current,
            "filled_slots":  filled,
            "total_slots":   168,
            "learn_pct":     round(filled / 168 * 100, 1),
            "reliable":      filled >= 48,
        }
