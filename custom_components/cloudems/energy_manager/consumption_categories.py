"""
CloudEMS Verbruik Categorieën — v1.0.0

Groepeert NILM-apparaten in betekenisvolle verbruikscategorieën
en berekent hun aandeel in het totale dagverbruik.

Categorieën:
  🔥 verwarming    — heat_pump, boiler, cv_boiler, heat, electric_heater
  🚗 mobiliteit    — ev_charger, micro_ev_charger
  🫧 wit_goed      — washing_machine, dishwasher, dryer
  🍳 keuken        — oven, microwave, induction, kitchen
  📺 entertainment — entertainment, light, garden
  ❄️  koeling       — refrigerator
  🔌 altijd_aan    — standby (via home_baseline)
  🔧 overig        — unknown, resistive, motor, power_tool, medical

Databronnen:
  1. NILM device-lijst (current_power × is_on → actueel)
  2. Home baseline (standby → 'altijd-aan' categorie)
  3. Historische accumulatie (dag-totalen per categorie)

Sensor-output:
  State: meest verbruikende categorie vandaag
  Attributen:
    - breakdown_pct: {verwarming: 38, mobiliteit: 22, ...}
    - breakdown_kwh: {verwarming: 4.2, ...}
    - top_category: "verwarming"
    - pie_data: lijst voor Lovelace grafiek

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

STORAGE_KEY     = "cloudems_categories_v1"
STORAGE_VERSION = 1
SAVE_INTERVAL_S = 300

# NILM device_type → categorie
DEVICE_CATEGORY: dict[str, str] = {
    # Verwarming
    "heat_pump":        "verwarming",
    "boiler":           "verwarming",
    "cv_boiler":        "verwarming",
    "heat":             "verwarming",
    "electric_heater":  "verwarming",
    # Mobiliteit
    "ev_charger":       "mobiliteit",
    "micro_ev_charger": "mobiliteit",
    # Wit goed
    "washing_machine":  "wit_goed",
    "dishwasher":       "wit_goed",
    "dryer":            "wit_goed",
    # Keuken
    "oven":             "keuken",
    "microwave":        "keuken",
    "induction":        "keuken",
    "kitchen":          "keuken",
    # Entertainment / licht
    "entertainment":    "entertainment",
    "light":            "entertainment",
    "garden":           "entertainment",
    # Koeling
    "refrigerator":     "koeling",
    # Overig
    "resistive":        "overig",
    "motor":            "overig",
    "power_tool":       "overig",
    "medical":          "overig",
    "solar_inverter":   "overig",
    "unknown":          "overig",
}

ALL_CATEGORIES = [
    "verwarming", "mobiliteit", "wit_goed", "keuken",
    "entertainment", "koeling", "altijd_aan", "overig",
]

CATEGORY_EMOJI = {
    "verwarming":    "🔥",
    "mobiliteit":    "🚗",
    "wit_goed":      "🫧",
    "keuken":        "🍳",
    "entertainment": "📺",
    "koeling":       "❄️",
    "altijd_aan":    "🔌",
    "overig":        "🔧",
}


@dataclass
class CategoryData:
    """Output voor de HA-sensor."""
    top_category:     str
    top_category_pct: float
    breakdown_pct:    dict[str, float]   # cat → %
    breakdown_kwh:    dict[str, float]   # cat → kWh vandaag
    breakdown_w_now:  dict[str, float]   # cat → W op dit moment
    total_w_now:      float
    total_kwh_today:  float
    pie_data:         list[dict]         # [{name, kwh, pct, emoji}]
    dominant_insight: str                # bijv. "Verwarming domineert: 38% van verbruik"
    # Historische gemiddelden (30 dagen)
    avg_breakdown_pct: dict[str, float]


class ConsumptionCategoryTracker:
    """
    Groepeert NILM-apparaten per categorie en accumuleert dag-totalen.

    Aanroep vanuit coordinator:
        tracker.tick(nilm_devices, standby_w, grid_import_w)
        data = tracker.get_data()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Dag-accumulatoren (kWh per categorie)
        self._today_date = ""
        self._today_kwh:  dict[str, float] = {c: 0.0 for c in ALL_CATEGORIES}

        # Lopend: W per categorie (voor real-time weergave)
        self._now_w: dict[str, float] = {c: 0.0 for c in ALL_CATEGORIES}

        # 30-daagse historiek: [{date, breakdown_kwh: {cat: kwh}}]
        self._history: list[dict] = []

        self._tick_s   = 10.0
        self._dirty    = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        saved_date = saved.get("today_date", "")
        if saved_date == today:
            self._today_date = today
            saved_kwh = saved.get("today_kwh", {})
            for c in ALL_CATEGORIES:
                self._today_kwh[c] = float(saved_kwh.get(c, 0.0))
        else:
            self._today_date = today
        self._history = saved.get("history", [])[-30:]
        _LOGGER.info("ConsumptionCategories: %d dagen historiek geladen", len(self._history))

    def tick(
        self,
        nilm_devices:  list[dict],
        standby_w:     float = 0.0,
        grid_import_w: float = 0.0,
    ) -> None:
        """
        Verwerk huidige NILM-status (elke 10s).

        nilm_devices : lijst van NILM device-dicts (uit coordinator)
        standby_w    : geleerde standby (uit home_baseline)
        grid_import_w: totale nettoimport voor 'onbekend' rest
        """
        now   = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        if today != self._today_date:
            # Sla vorige dag op in historiek
            if self._today_date and sum(self._today_kwh.values()) > 0.1:
                self._history.append({
                    "date":         self._today_date,
                    "breakdown_kwh": {c: round(v, 3) for c, v in self._today_kwh.items()},
                })
                self._history = self._history[-30:]
            self._today_date = today
            self._today_kwh  = {c: 0.0 for c in ALL_CATEGORIES}
            self._dirty      = True

        # ── Real-time W per categorie ──────────────────────────────────────
        now_w: dict[str, float] = {c: 0.0 for c in ALL_CATEGORIES}

        # NILM actieve apparaten
        nilm_total_w = 0.0
        for dev in nilm_devices:
            if not dev.get("is_on"):
                continue
            dtype = dev.get("device_type", "unknown")
            cat   = DEVICE_CATEGORY.get(dtype, "overig")
            pw    = float(dev.get("current_power") or 0)
            now_w[cat] += pw
            nilm_total_w += pw

        # Standby → altijd_aan
        now_w["altijd_aan"] = max(0.0, standby_w)

        # Niet-verklaarde rest → overig
        identified_w = sum(now_w.values())
        rest_w = max(0.0, grid_import_w - identified_w)
        now_w["overig"] = max(now_w.get("overig", 0.0), rest_w * 0.5)  # 50% van onverklaard naar overig

        self._now_w = now_w

        # ── Accumulatie (kWh) ──────────────────────────────────────────────
        dt_h = self._tick_s / 3600.0
        for cat, w in now_w.items():
            self._today_kwh[cat] += w / 1000.0 * dt_h

        self._dirty = True

    def get_data(self) -> CategoryData:
        total_kwh = sum(self._today_kwh.values())
        total_w   = sum(self._now_w.values())

        # Percentages vandaag
        breakdown_pct: dict[str, float] = {}
        for cat in ALL_CATEGORIES:
            kwh = self._today_kwh.get(cat, 0.0)
            breakdown_pct[cat] = round(kwh / total_kwh * 100, 1) if total_kwh > 0.1 else 0.0

        # Top-categorie
        top_cat = max(ALL_CATEGORIES, key=lambda c: self._today_kwh.get(c, 0.0))
        top_pct = breakdown_pct.get(top_cat, 0.0)

        # Pie-data (alleen categorieën met > 1%)
        pie_data = [
            {
                "name":  f"{CATEGORY_EMOJI.get(cat,'·')} {cat.replace('_', ' ').capitalize()}",
                "kwh":   round(self._today_kwh.get(cat, 0.0), 2),
                "pct":   breakdown_pct[cat],
                "emoji": CATEGORY_EMOJI.get(cat, "·"),
                "w_now": round(self._now_w.get(cat, 0.0), 0),
            }
            for cat in ALL_CATEGORIES
            if breakdown_pct.get(cat, 0.0) > 1.0
        ]
        pie_data.sort(key=lambda x: -x["pct"])

        # 30-daagse gemiddelden
        avg_pct: dict[str, float] = {c: 0.0 for c in ALL_CATEGORIES}
        if self._history:
            for record in self._history:
                bk = record.get("breakdown_kwh", {})
                rec_total = sum(bk.values()) or 1.0
                for c in ALL_CATEGORIES:
                    avg_pct[c] += bk.get(c, 0.0) / rec_total * 100
            n = len(self._history)
            avg_pct = {c: round(v / n, 1) for c, v in avg_pct.items()}

        # Inzicht
        top_label = top_cat.replace("_", " ")
        if total_kwh < 0.5:
            insight = "Verbruikscategorieën worden opgebouwd gedurende de dag."
        elif top_pct > 50:
            insight = (
                f"{CATEGORY_EMOJI.get(top_cat,'·')} {top_label.capitalize()} domineert: "
                f"{top_pct:.0f}% van huidig dagverbruik ({self._today_kwh.get(top_cat,0):.1f} kWh)."
            )
        elif top_pct > 30:
            insight = (
                f"Grootste verbruiker: {CATEGORY_EMOJI.get(top_cat,'·')} {top_label} "
                f"({top_pct:.0f}%). "
                f"Gevolgd door {CATEGORY_EMOJI.get(self._second_cat(),'·')} "
                f"{self._second_cat().replace('_',' ')} "
                f"({breakdown_pct.get(self._second_cat(),0):.0f}%)."
            )
        else:
            insight = f"Verbruik gelijkmatig verdeeld. Totaal vandaag: {total_kwh:.1f} kWh."

        return CategoryData(
            top_category      = top_cat,
            top_category_pct  = top_pct,
            breakdown_pct     = breakdown_pct,
            breakdown_kwh     = {c: round(v, 2) for c, v in self._today_kwh.items()},
            breakdown_w_now   = {c: round(v, 0) for c, v in self._now_w.items()},
            total_w_now       = round(total_w, 0),
            total_kwh_today   = round(total_kwh, 2),
            pie_data          = pie_data,
            dominant_insight  = insight,
            avg_breakdown_pct = avg_pct,
        )

    def _second_cat(self) -> str:
        """Tweede meest verbruikende categorie."""
        sorted_cats = sorted(ALL_CATEGORIES, key=lambda c: self._today_kwh.get(c, 0.0), reverse=True)
        return sorted_cats[1] if len(sorted_cats) > 1 else "overig"

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "today_date": self._today_date,
                "today_kwh":  {c: round(v, 4) for c, v in self._today_kwh.items()},
                "history":    self._history,
            })
            self._dirty     = False
            self._last_save = time.time()
