# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Sub-device definities (v1.0.0).

Elke logische groep CloudEMS-entiteiten krijgt een eigen sub-device in HA.
Zo verschijnen gerelateerde entiteiten netjes gegroepeerd onder een
bovenliggende map in het HA apparatenregister.

Hiërarchie
──────────
  CloudEMS Energy Manager          ← hoofd-apparaat  (entry_id)
    ├── CloudEMS NILM Bediening    ← NILM bevestig/afwijs-knoppen
    ├── CloudEMS Rolluiken         ← rolluik actie-knoppen + module-schakelaar
    ├── CloudEMS PV Dimmer         ← omvormer dimmer schakelaars + sliders
    ├── CloudEMS Zonne-energie     ← omvormer profiel/clipping sensoren
    └── CloudEMS Zone Klimaat      ← per-zone klimaat sensoren

Gebruik
───────
    from .sub_devices import sub_device_info, SUB_NILM, SUB_SHUTTER, SUB_PV_DIMMER, ...

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_SHUTTER)
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER, VERSION

# ── Sub-device type sleutels ─────────────────────────────────────────────────

SUB_NILM        = "nilm_control"      # NILM bevestig/afwijs-knoppen
SUB_SHUTTER     = "shutter_control"   # Rolluik actie-knoppen, tijden, setpoints + module-schakelaar
SUB_PV_DIMMER   = "pv_dimmer"         # PV dimmer schakelaars + sliders
SUB_SOLAR       = "solar"             # Omvormer profiel + clipping sensoren
SUB_ZONE_CLIMATE = "zone_climate"     # Per-zone klimaat sensoren
SUB_BOILER      = "boiler"            # Warm-water boiler status, kalk, thermisch model
SUB_PRICE       = "price"             # Energieprijzen: huidig, goedkoop, EPEX, tarieven
SUB_LAMP        = "lamp"              # Lampcirculatie sturing + module-schakelaar
SUB_BATTERY     = "battery"           # Batterijopslag status & sturing
SUB_GRID        = "grid"              # Net & fase-monitoring

# ── Sub-device metadata ──────────────────────────────────────────────────────

_SUB_DEVICE_META: dict[str, tuple[str, str]] = {
    #  sleutel         → (weergavenaam,               icon-hint)
    SUB_NILM:          ("CloudEMS NILM Bediening",     "mdi:home-analytics"),
    SUB_SHUTTER:       ("CloudEMS Rolluiken",           "mdi:window-shutter"),
    SUB_PV_DIMMER:     ("CloudEMS PV Dimmer",          "mdi:solar-power"),
    SUB_SOLAR:         ("CloudEMS Zonne-energie",      "mdi:solar-panel-large"),
    SUB_ZONE_CLIMATE:  ("CloudEMS Zone Klimaat",       "mdi:home-thermometer"),
    SUB_BOILER:        ("CloudEMS Warm Water",         "mdi:water-boiler"),
    SUB_PRICE:         ("CloudEMS Energieprijzen",     "mdi:currency-eur"),
    SUB_LAMP:          ("CloudEMS Lampcirculatie",     "mdi:lightbulb-group"),
    SUB_BATTERY:       ("CloudEMS Batterij",              "mdi:battery-charging"),
    SUB_GRID:          ("CloudEMS Net & Fasen",           "mdi:transmission-tower"),

}


def sub_device_info(entry: ConfigEntry, sub_type: str) -> DeviceInfo:
    """Geeft een DeviceInfo terug voor het opgegeven sub-device type.

    Het sub-device wordt automatisch als kind van het hoofd-apparaat
    (entry.entry_id) geplaatst via ``via_device``.

    Args:
        entry:    De CloudEMS config entry.
        sub_type: Een van de SUB_* constanten uit dit module.

    Returns:
        DeviceInfo voor gebruik als ``device_info`` property.
    """
    display_name, _ = _SUB_DEVICE_META.get(sub_type, (f"CloudEMS {sub_type}", ""))
    return DeviceInfo(
        identifiers  = {(DOMAIN, f"{entry.entry_id}_{sub_type}")},
        name         = display_name,
        manufacturer = MANUFACTURER,
        model        = f"CloudEMS v{VERSION}",
        via_device   = (DOMAIN, entry.entry_id),
    )
