# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — Getypte configuratie via dataclasses — v1.0.0

Vervangt verspreid gebruik van config.get("key", default) met een centrale,
volledig getypte configuratiedataclass. Voordelen:
  • IDE-autocompletion (geen typo's meer in key-strings)
  • Type-validatie bij startup — verkeerde waarden geven duidelijke foutmelding
  • Eén plek voor alle defaults
  • Makkelijker te testen

Gebruik:
    cfg = CloudEMSConfig.from_dict(config)
    if cfg.battery.capacity_kwh > 0:
        scheduler.setup(cfg.battery)

Validatie:
    errors = cfg.validate()
    if errors:
        _LOGGER.warning("Config problemen: %s", errors)

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)


# ── Sub-configuraties ─────────────────────────────────────────────────────────

@dataclass
class BatteryConfig:
    """Batterij-configuratie."""
    entity_id:              str   = ""
    capacity_kwh:           float = 10.0
    max_charge_power_w:     float = 3000.0
    max_discharge_power_w:  float = 3000.0
    min_soc_pct:            float = 10.0
    max_soc_pct:            float = 90.0
    chemistry:              str   = "NMC"    # LFP / NMC / NCA / LTO
    price_eur:              float = 0.0      # aanschafprijs voor degradatieberekening
    round_trip_efficiency:  float = 0.92

    @property
    def enabled(self) -> bool:
        return bool(self.entity_id)

    def validate(self) -> list[str]:
        errors = []
        if self.capacity_kwh <= 0:
            errors.append("battery.capacity_kwh moet > 0 zijn")
        if not 0 < self.min_soc_pct < self.max_soc_pct < 100:
            errors.append("battery.min_soc_pct < max_soc_pct vereist")
        if self.chemistry not in ("LFP", "NMC", "NCA", "LTO"):
            errors.append(f"battery.chemistry onbekend: {self.chemistry}")
        return errors


@dataclass
class EVConfig:
    """EV-lader configuratie."""
    charger_entity_id:      str   = ""
    current_entity_id:      str   = ""
    min_current_a:          float = 6.0
    max_current_a:          float = 16.0
    phases:                 int   = 1
    voltage_v:              float = 230.0
    target_soc_pct:         float = 80.0
    ere_tracking_enabled:   bool  = False
    mid_meter_entity_id:    str   = ""

    @property
    def enabled(self) -> bool:
        return bool(self.charger_entity_id)

    @property
    def max_power_w(self) -> float:
        return self.max_current_a * self.phases * self.voltage_v

    def validate(self) -> list[str]:
        errors = []
        if self.min_current_a < 6:
            errors.append("ev.min_current_a moet minimaal 6 A zijn")
        if self.max_current_a > 32:
            errors.append("ev.max_current_a mag maximaal 32 A zijn")
        if self.phases not in (1, 3):
            errors.append("ev.phases moet 1 of 3 zijn")
        return errors


@dataclass
class PVConfig:
    """Zonnepaneel-configuratie."""
    inverter_entity_ids:    list[str] = field(default_factory=list)
    peak_power_wp:          float = 0.0      # 0 = auto-detectie
    orientation_degrees:    float = 180.0    # 180 = zuidgericht
    tilt_degrees:           float = 35.0
    export_limit_entity_id: str   = ""

    @property
    def enabled(self) -> bool:
        return bool(self.inverter_entity_ids)

    def validate(self) -> list[str]:
        errors = []
        if self.peak_power_wp < 0:
            errors.append("pv.peak_power_wp mag niet negatief zijn")
        return errors


@dataclass
class GridConfig:
    """Netaansluiting configuratie."""
    p1_entity_id:           str   = ""
    phase_l1_entity_id:     str   = ""
    phase_l2_entity_id:     str   = ""
    phase_l3_entity_id:     str   = ""
    fuse_a:                 float = 25.0     # hoofdzekering (A)
    max_import_kw:          float = 0.0      # 0 = auto (fuse_a * 230 * phases / 1000)
    country:                str   = "NL"
    postal_code:            str   = ""

    @property
    def has_p1(self) -> bool:
        return bool(self.p1_entity_id)

    @property
    def has_phases(self) -> bool:
        return bool(self.phase_l1_entity_id)

    @property
    def phases(self) -> int:
        if self.phase_l3_entity_id:
            return 3
        if self.phase_l2_entity_id:
            return 2
        return 1

    def validate(self) -> list[str]:
        errors = []
        if self.fuse_a < 10:
            errors.append("grid.fuse_a lijkt erg laag (< 10 A)")
        if self.country not in ("NL", "BE", "DE", "AT", "FR", "NO", "SE", "DK", "FI"):
            errors.append(f"grid.country onbekend: {self.country}")
        return errors


@dataclass
class PriceConfig:
    """Energieprijzen configuratie."""
    epex_country:           str   = "NL"
    entso_e_api_key:        str   = ""
    mijnbatterij_api_key:   str   = ""   # API key van mijnbatterij.nl voor ranking
    battery_room_temp_sensor: str = ""  # entity_id thermometer in accu-ruimte (bijv. sensor.accu_temp)
    battery_room_heater_w:  float = 1500.0  # vermogen verwarmer in accu-ruimte (W)
    battery_room_climate_entity: str = ""  # climate.accu_ruimte of switch.accu_verwarmer
    battery_room_auto_heat: bool  = False
    battery_purchase_price_eur: float = 0.0  # 0 = automatisch schatten
    battery_purchase_date:  str   = ""        # ISO date e.g. 2023-03-15
    zonneplan_sensor_today:    str = ""  # auto-discovered, override if needed
    zonneplan_sensor_total:    str = ""
    zonneplan_sensor_delivery: str = ""
    zonneplan_sensor_charge:   str = ""
    zonneplan_sensor_month:    str = ""
    zonneplan_sensor_year:     str = ""    # True = CloudEMS stuurt verwarmer automatisch
    import_tariff_eur:      float = 0.0      # vast tarief override (0 = gebruik EPEX)
    export_tariff_eur:      float = 0.0
    standing_charge_eur_day: float = 0.50
    vat_pct:                float = 21.0
    dynamic_pricing:        bool  = True

    def validate(self) -> list[str]:
        errors = []
        if self.vat_pct < 0 or self.vat_pct > 100:
            errors.append("price.vat_pct moet tussen 0 en 100 zijn")
        return errors


@dataclass
class AIConfig:
    """AI/NILM classificatie configuratie."""
    provider:               str   = "none"   # none / local / cloud / ollama
    ollama_host:            str   = "http://localhost:11434"
    ollama_model:           str   = "mistral"
    cloud_api_key:          str   = ""

    def validate(self) -> list[str]:
        errors = []
        if self.provider not in ("none", "local", "cloud", "ollama"):
            errors.append(f"ai.provider onbekend: {self.provider}")
        return errors


@dataclass
class NotificationConfig:
    """Notificatie configuratie."""
    notify_service:         str   = ""       # bijv. notify.mobile_app_telefoon
    daily_summary_enabled:  bool  = True
    weekly_insights_enabled: bool = True
    congestion_alerts:      bool  = True

    def validate(self) -> list[str]:
        return []


# ── Hoofd-configuratie ────────────────────────────────────────────────────────

@dataclass
class CloudEMSConfig:
    """
    Centrale CloudEMS configuratie — volledig getypt.

    Aanmaken vanuit HA config dict:
        cfg = CloudEMSConfig.from_dict(hass_config_entry.data)

    Alle modules gebruiken de relevante sub-config:
        scheduler.setup(cfg.battery)
        pv_forecast.setup(cfg.pv)
    """
    battery:       BatteryConfig      = field(default_factory=BatteryConfig)
    ev:            EVConfig           = field(default_factory=EVConfig)
    pv:            PVConfig           = field(default_factory=PVConfig)
    grid:          GridConfig         = field(default_factory=GridConfig)
    price:         PriceConfig        = field(default_factory=PriceConfig)
    ai:            AIConfig           = field(default_factory=AIConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)

    # Feature toggles
    nilm_enabled:          bool = True
    battery_enabled:       bool = True
    ev_enabled:            bool = True
    boiler_enabled:        bool = True
    shutter_enabled:       bool = True
    pool_enabled:          bool = False
    micro_mobility_enabled: bool = False
    lamp_circulation_enabled: bool = False
    ere_enabled:           bool = False
    belgium_capacity_enabled: bool = False

    # Algemeen
    update_interval_s:     int  = 10
    advanced_mode:         bool = False
    debug_logging:         bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "CloudEMSConfig":
        """Maak een CloudEMSConfig aan vanuit een HA config dict."""
        cfg = cls()

        # Grid
        cfg.grid = GridConfig(
            p1_entity_id           = data.get("p1_sensor", ""),
            phase_l1_entity_id     = data.get("phase_l1_sensor", ""),
            phase_l2_entity_id     = data.get("phase_l2_sensor", ""),
            phase_l3_entity_id     = data.get("phase_l3_sensor", ""),
            fuse_a                 = float(data.get("main_fuse_a", 25)),
            country                = data.get("country", "NL"),
            postal_code            = str(data.get("postal_code", "")),
        )

        # PV
        inv_ids = data.get("inverter_sensors", [])
        if isinstance(inv_ids, str):
            inv_ids = [inv_ids] if inv_ids else []
        cfg.pv = PVConfig(
            inverter_entity_ids    = inv_ids,
            peak_power_wp          = float(data.get("pv_peak_power_wp", 0)),
            orientation_degrees    = float(data.get("pv_orientation", 180)),
            tilt_degrees           = float(data.get("pv_tilt", 35)),
            export_limit_entity_id = data.get("export_limit_entity", ""),
        )

        # Battery
        cfg.battery = BatteryConfig(
            entity_id              = data.get("battery_soc_sensor", ""),
            capacity_kwh           = float(data.get("battery_capacity_kwh", 10)),
            max_charge_power_w     = float(data.get("battery_max_charge_w", 3000)),
            max_discharge_power_w  = float(data.get("battery_max_discharge_w", 3000)),
            min_soc_pct            = float(data.get("battery_min_soc", 10)),
            max_soc_pct            = float(data.get("battery_max_soc", 90)),
            chemistry              = data.get("battery_chemistry", "NMC"),
            price_eur              = float(data.get("battery_price_eur", 0)),
            round_trip_efficiency  = float(data.get("battery_round_trip_efficiency", 0.92)),
        )

        # EV
        cfg.ev = EVConfig(
            charger_entity_id      = data.get("ev_charger_entity", ""),
            current_entity_id      = data.get("ev_current_entity", ""),
            min_current_a          = float(data.get("ev_min_current_a", 6)),
            max_current_a          = float(data.get("ev_max_current_a", 16)),
            phases                 = int(data.get("ev_phases", 1)),
            voltage_v              = float(data.get("ev_voltage_v", 230)),
            ere_tracking_enabled   = bool(data.get("ere_tracking_enabled", False)),
            mid_meter_entity_id    = data.get("ere_mid_meter_entity", ""),
        )

        # Prijzen
        cfg.price = PriceConfig(
            epex_country           = data.get("epex_country", data.get("country", "NL")),
            entso_e_api_key        = data.get("entso_e_api_key", ""),
            mijnbatterij_api_key   = data.get("mijnbatterij_api_key", ""),
            battery_room_temp_sensor = data.get("battery_room_temp_sensor", ""),
            battery_room_heater_w    = float(data.get("battery_room_heater_w", 1500.0)),
            battery_room_climate_entity = data.get("battery_room_climate_entity", ""),
            battery_room_auto_heat      = bool(data.get("battery_room_auto_heat", False)),
            battery_purchase_price_eur  = float(data.get("battery_purchase_price_eur") or 0),
            battery_purchase_date       = str(data.get("battery_purchase_date", "")),
            zonneplan_sensor_today      = str(data.get("zonneplan_sensor_today", "")),
            zonneplan_sensor_total      = str(data.get("zonneplan_sensor_total", "")),
            zonneplan_sensor_delivery   = str(data.get("zonneplan_sensor_delivery", "")),
            zonneplan_sensor_charge     = str(data.get("zonneplan_sensor_charge", "")),
            zonneplan_sensor_month      = str(data.get("zonneplan_sensor_month", "")),
            zonneplan_sensor_year       = str(data.get("zonneplan_sensor_year", "")),
            import_tariff_eur      = float(data.get("import_tariff_eur_kwh", 0)),
            export_tariff_eur      = float(data.get("export_tariff_eur_kwh", 0)),
            standing_charge_eur_day = float(data.get("standing_charge_eur_day", 0.50)),
            vat_pct                = float(data.get("vat_pct", 21)),
            dynamic_pricing        = bool(data.get("dynamic_pricing", True)),
        )

        # AI
        cfg.ai = AIConfig(
            provider               = data.get("ai_provider", "none"),
            ollama_host            = data.get("ollama_host", "http://localhost:11434"),
            ollama_model           = data.get("ollama_model", "mistral"),
            cloud_api_key          = data.get("cloud_ai_api_key", ""),
        )

        # Notificaties
        cfg.notifications = NotificationConfig(
            notify_service         = data.get("notify_service", ""),
            daily_summary_enabled  = bool(data.get("daily_summary_enabled", True)),
            weekly_insights_enabled = bool(data.get("weekly_insights_enabled", True)),
            congestion_alerts      = bool(data.get("congestion_alerts_enabled", True)),
        )

        # Feature flags
        cfg.nilm_enabled           = bool(data.get("nilm_enabled", True))
        cfg.battery_enabled        = bool(data.get("battery_enabled", cfg.battery.enabled))
        cfg.ev_enabled             = bool(data.get("ev_enabled", cfg.ev.enabled))
        cfg.boiler_enabled         = bool(data.get("boiler_enabled", False))
        cfg.shutter_enabled        = bool(data.get("shutter_enabled", False))
        cfg.pool_enabled           = bool(data.get("pool_enabled", False))
        cfg.micro_mobility_enabled = bool(data.get("micro_mobility_enabled", False))
        cfg.lamp_circulation_enabled = bool(data.get("lamp_circulation_enabled", False))
        cfg.ere_enabled            = bool(data.get("ere_enabled", cfg.ev.ere_tracking_enabled))
        cfg.belgium_capacity_enabled = (cfg.grid.country == "BE")

        # Algemeen
        cfg.update_interval_s      = int(data.get("update_interval_s", 10))
        cfg.advanced_mode          = bool(data.get("advanced_mode", False))
        cfg.debug_logging          = bool(data.get("debug_logging", False))

        return cfg

    def validate(self) -> list[str]:
        """Valideer de volledige configuratie. Geeft lijst van waarschuwingen/fouten."""
        errors: list[str] = []
        errors.extend(self.grid.validate())
        errors.extend(self.battery.validate())
        errors.extend(self.ev.validate())
        errors.extend(self.pv.validate())
        errors.extend(self.price.validate())
        errors.extend(self.ai.validate())
        errors.extend(self.notifications.validate())
        return errors

    def to_dict(self) -> dict:
        """Exporteer config als dict (voor diagnose/logging)."""
        return {
            "grid":    {f.name: getattr(self.grid, f.name) for f in fields(self.grid)},
            "battery": {f.name: getattr(self.battery, f.name) for f in fields(self.battery)},
            "ev":      {f.name: getattr(self.ev, f.name) for f in fields(self.ev)},
            "pv":      {f.name: getattr(self.pv, f.name) for f in fields(self.pv)},
            "price":   {f.name: getattr(self.price, f.name) for f in fields(self.price)},
            "ai":      {f.name: getattr(self.ai, f.name) for f in fields(self.ai)},
        }
