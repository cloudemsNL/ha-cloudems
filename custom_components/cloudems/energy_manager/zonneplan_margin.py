# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS
"""
ZonneplanMarginCalculator — v1.0.0

Calculates Zonneplan's margin on battery imbalance market participation
by comparing what Zonneplan credits vs what Tennet actually pays.

Data sources:
  Zonneplan integration sensors:
    sensor.*_today          → today's earnings (EUR) — what Zonneplan credits
    sensor.*_total          → all-time earnings (EUR)
    sensor.*_delivery_today → kWh discharged today
    sensor.*_production_today → kWh charged today
    sensor.*_result_this_month → monthly result with daily breakdown
    sensor.*_result_this_year  → yearly result with monthly breakdown

  Tennet imbalance prices (from TennetImbalanceSignal):
    up_price_eur_mwh   → what Tennet pays for up-regulation (€/MWh)
    down_price_eur_mwh → what Tennet pays for down-regulation (€/MWh)

Margin calculation:
  Zonneplan effective rate = total_day_eur / net_kwh (€/kWh)
  Tennet rate              = up_price / 1000 (€/kWh, during activation)
  Margin                   = (tennet_rate - zonneplan_rate) / tennet_rate × 100%

Auto-discovery:
  Searches HA states for sensors matching Zonneplan battery patterns.
  Falls back to user-configured entity IDs.
"""
from __future__ import annotations

import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Candidate entity ID patterns for auto-discovery
ZONNEPLAN_TODAY_PATTERNS    = ["_today"]
ZONNEPLAN_TOTAL_PATTERNS    = ["_total", "_total_earned"]
ZONNEPLAN_DELIVERY_PATTERNS = ["_delivery_today", "_delivery_day"]
ZONNEPLAN_CHARGE_PATTERNS   = ["_production_today", "_production_day"]
ZONNEPLAN_MONTH_PATTERNS    = ["_result_this_month"]
ZONNEPLAN_YEAR_PATTERNS         = ["_result_this_year"]
ZONNEPLAN_FIRST_MEASURED_PATTERNS = ["_first_measured", "_first_measured_at"]


class ZonneplanMarginCalculator:
    """
    Reads Zonneplan earnings sensors and compares with Tennet imbalance prices
    to estimate Zonneplan's margin on battery market participation.
    """

    def __init__(self, hass, config: dict) -> None:
        self._hass   = hass
        self._config = config

        # Configurable sensor IDs (with auto-discovery fallback)
        self._sensor_today    = config.get("zonneplan_sensor_today", "")
        self._sensor_total    = config.get("zonneplan_sensor_total", "")
        self._sensor_delivery = config.get("zonneplan_sensor_delivery", "")
        self._sensor_charge   = config.get("zonneplan_sensor_charge", "")
        self._sensor_month    = config.get("zonneplan_sensor_month", "")
        self._sensor_year     = config.get("zonneplan_sensor_year", "")

        # Discovered IDs cached after first successful discovery
        self._discovered: dict[str, str] = {}

    def _discover_sensors(self) -> dict[str, str]:
        """
        Auto-discover Zonneplan battery sensors from HA state machine.
        Looks for monetary sensors with 'zonneplan' in entity_id.
        """
        if self._discovered:
            return self._discovered

        result: dict[str, str] = {}
        all_states = self._hass.states.async_all("sensor")

        # Filter to Zonneplan sensors
        zp_states = [
            s for s in all_states
            if "zonneplan" in s.entity_id.lower()
        ]

        def _find(states, patterns: list[str]) -> Optional[str]:
            for s in states:
                eid = s.entity_id.lower()
                for pat in patterns:
                    if eid.endswith(pat):
                        return s.entity_id
            return None

        result["today"]    = self._sensor_today    or _find(zp_states, ZONNEPLAN_TODAY_PATTERNS)    or ""
        result["total"]    = self._sensor_total    or _find(zp_states, ZONNEPLAN_TOTAL_PATTERNS)    or ""
        result["delivery"] = self._sensor_delivery or _find(zp_states, ZONNEPLAN_DELIVERY_PATTERNS) or ""
        result["charge"]   = self._sensor_charge   or _find(zp_states, ZONNEPLAN_CHARGE_PATTERNS)   or ""
        result["month"]    = self._sensor_month    or _find(zp_states, ZONNEPLAN_MONTH_PATTERNS)    or ""
        result["year"]       = self._sensor_year     or _find(zp_states, ZONNEPLAN_YEAR_PATTERNS)           or ""
        result["first_measured"] = _find(zp_states, ZONNEPLAN_FIRST_MEASURED_PATTERNS) or ""

        if result["today"]:
            self._discovered = result
            _LOGGER.info(
                "ZonneplanMargin: discovered sensors — "
                "today=%s, total=%s, delivery=%s, charge=%s, month=%s, year=%s",
                result["today"], result["total"], result["delivery"],
                result["charge"], result["month"], result["year"],
            )
        else:
            zp_names = [s.entity_id for s in zp_states[:10]]
            _LOGGER.warning(
                "ZonneplanMargin: no sensors found. "
                "Zonneplan sensors visible in HA: %s. "
                "Install ha-zonneplan-one integration.",
                zp_names if zp_names else "NONE — check integration",
            )
        return result  # v5.5.305: tennet_data berekening verwijderd — hoort niet in _discover_sensors (tennet_data niet in scope → NameError). Zit al correct in calculate().

    def _read_sensor(self, entity_id: str) -> Optional[float]:
        """Read a sensor state as float."""
        if not entity_id:
            return None
        try:
            state = self._hass.states.get(entity_id)
            if state and state.state not in ("unavailable", "unknown", "None", None):
                return float(state.state)
        except (ValueError, TypeError):
            pass
        return None

    def _read_attrs(self, entity_id: str) -> dict:
        """Read sensor attributes."""
        if not entity_id:
            return {}
        try:
            state = self._hass.states.get(entity_id)
            return state.attributes if state else {}
        except Exception:
            return {}

    def calculate(self,
                  tennet_up_price_mwh:   float,
                  tennet_down_price_mwh: float,
                  our_discharge_kwh:     float,
                  our_charge_kwh:        float) -> dict:
        """
        Calculate Zonneplan's margin vs Tennet imbalance prices.

        Args:
            tennet_up_price_mwh:   Tennet up-regulation price (€/MWh)
            tennet_down_price_mwh: Tennet down-regulation price (€/MWh)
            our_discharge_kwh:     kWh we discharged (from CloudEMS tracking)
            our_charge_kwh:        kWh we charged (from CloudEMS tracking)

        Returns:
            Dict with earnings comparison and margin breakdown.
        """
        sensors = self._discover_sensors()

        # Read Zonneplan earnings
        zp_today_eur    = self._read_sensor(sensors.get("today", ""))
        zp_total_eur    = self._read_sensor(sensors.get("total", ""))
        zp_delivery_kwh = self._read_sensor(sensors.get("delivery", ""))
        zp_charge_kwh   = self._read_sensor(sensors.get("charge", ""))
        month_attrs     = self._read_attrs(sensors.get("month", ""))
        year_attrs      = self._read_attrs(sensors.get("year", ""))

        # Read installation date from first_measured_at sensor
        first_measured_eid = sensors.get("first_measured", "")
        install_date = None
        days_since_install = None
        if first_measured_eid:
            try:
                fm_state = self._hass.states.get(first_measured_eid)
                if fm_state and fm_state.state not in ("unavailable", "unknown", None):
                    from datetime import datetime, date, timezone
                    fm_dt = datetime.fromisoformat(fm_state.state.replace("Z", "+00:00"))
                    install_date = fm_dt.date().isoformat()
                    days_since_install = (date.today() - fm_dt.date()).days
            except Exception as e:
                _LOGGER.debug("first_measured_at parse error: %s", e)

        if zp_today_eur is None:
            return {
                "configured":       False,
                "reason":           "Zonneplan sensors not found — configure zonneplan_sensor_today",
                "discovered":       sensors,
                "install_date":     install_date,
                "days_since_install": days_since_install,
            }

        # Zonneplan's effective rate today
        # Use Zonneplan's own delivery/charge numbers if available, else ours
        discharge_kwh = zp_delivery_kwh or our_discharge_kwh
        charge_kwh    = zp_charge_kwh   or our_charge_kwh
        net_kwh       = max(0.001, discharge_kwh - charge_kwh)

        zp_effective_rate_kwh = zp_today_eur / net_kwh if net_kwh > 0.01 else 0.0

        # Tennet theoretical earnings for same kWh
        tennet_up_kwh   = tennet_up_price_mwh   / 1000   # €/kWh
        tennet_down_kwh = tennet_down_price_mwh / 1000

        # Theoretical revenue: discharge at up-price, charge saved at down-price
        theoretical_eur = (discharge_kwh * tennet_up_kwh) - (charge_kwh * tennet_down_kwh)
        theoretical_eur = max(0, theoretical_eur)

        # Margin
        margin_eur = max(0, theoretical_eur - zp_today_eur)
        margin_pct = (margin_eur / theoretical_eur * 100) if theoretical_eur > 0.001 else 0.0

        # Annualised value of margin (based on today's rate)
        days_tracked = max(1, self._count_tracked_days(year_attrs))
        avg_daily_margin = margin_eur   # today only for now; historical once we have data

        # Monthly breakdown from Zonneplan
        monthly_history = month_attrs.get("days", []) or []
        yearly_history  = year_attrs.get("months", []) or []

        return {
            "configured":             True,
            "sensors":                sensors,
            # Zonneplan earnings
            "zp_today_eur":           round(zp_today_eur, 4),
            "zp_total_eur":           round(zp_total_eur, 2) if zp_total_eur else None,
            "zp_discharge_kwh":       round(discharge_kwh, 3),
            "zp_charge_kwh":          round(charge_kwh, 3),
            "zp_effective_rate_ct":   round(zp_effective_rate_kwh * 100, 2),
            # Tennet theoretical
            "tennet_up_price_mwh":    round(tennet_up_price_mwh, 2),
            "tennet_down_price_mwh":  round(tennet_down_price_mwh, 2),
            "tennet_up_rate_ct":      round(tennet_up_kwh * 100, 2),
            "theoretical_eur":        round(theoretical_eur, 4),
            # Margin
            "margin_eur":             round(margin_eur, 4),
            "margin_pct":             round(margin_pct, 1),
            "margin_explanation":     (
                f"Zonneplan credits {zp_effective_rate_kwh*100:.1f}ct/kWh, "
                f"Tennet up-regulation pays {tennet_up_kwh*100:.1f}ct/kWh. "
                f"Estimated Zonneplan margin: {margin_pct:.0f}%."
            ) if tennet_up_price_mwh > 0 else "Waiting for Tennet price data.",
            # Historical
            "monthly_history":        monthly_history[-3:]  if isinstance(monthly_history, list) else [],
            "yearly_history":         yearly_history[-12:] if isinstance(yearly_history,  list) else [],
            # Installation date
            "install_date":           install_date,
            "days_since_install":     days_since_install,
        }

    def _count_tracked_days(self, year_attrs: dict) -> int:
        """Count days of data available from Zonneplan year sensor."""
        months = year_attrs.get("months", []) or []
        return sum(len(m.get("days", [])) for m in months if isinstance(m, dict))

    def to_dict(self, tennet_data: dict, imbalance_data: dict,
                bridge_earnings: dict | None = None) -> dict:
        """Generate margin report from current Tennet + imbalance + bridge data."""
        up_price   = float(tennet_data.get("up_price_eur_mwh", 0)   or 0)
        down_price = float(tennet_data.get("down_price_eur_mwh", 0) or 0)
        dis_kwh    = float(imbalance_data.get("today_discharge_kwh", 0) or 0)
        chg_kwh    = float(imbalance_data.get("today_charge_kwh", 0)    or 0)

        result = self.calculate(up_price, down_price, dis_kwh, chg_kwh)

        # Enrich with bridge earnings if available (overrides sensor discovery)
        if bridge_earnings and bridge_earnings.get("total_earned_eur", 0) > 0:
            result["configured"]      = True
            result["zp_today_eur"]    = round(bridge_earnings.get("today_eur", 0), 4)
            result["zp_total_eur"]    = round(bridge_earnings.get("total_earned_eur", 0), 2)
            result["zp_discharge_kwh"]= round(bridge_earnings.get("delivery_kwh", dis_kwh), 3)
            result["zp_charge_kwh"]   = round(bridge_earnings.get("charge_kwh", chg_kwh), 3)
            result["data_source"]     = "zonneplan_bridge"
            # Recalculate effective rate with real kwh
            zp_net = max(0.001, result["zp_discharge_kwh"] - result["zp_charge_kwh"])
            result["zp_effective_rate_ct"] = round(
                result["zp_today_eur"] / zp_net * 100, 2
            ) if zp_net > 0.01 else 0.0

        # v5.5.293: splits Zonneplan opbrengst in onbalans vs day-ahead component
        # Tennet betaalt: up_price * discharge_kwh - down_price * charge_kwh (onbalans)
        # Wat overblijft is day-ahead + overige markten (Zonneplan marge)
        _dis  = result.get("zp_discharge_kwh", 0) or 0
        _chg  = result.get("zp_charge_kwh", 0) or 0
        _up   = float(tennet_data.get("up_price_eur_mwh", 0) or 0) / 1000   # €/kWh
        _dn   = float(tennet_data.get("down_price_eur_mwh", 0) or 0) / 1000  # €/kWh
        _today = result.get("zp_today_eur", 0) or 0
        if _up > 0 or _dn > 0:
            _tennet_onbalans = round(max(0, _dis * _up - _chg * _dn), 4)
            _day_ahead       = round(max(0, _today - _tennet_onbalans), 4)
            result["tennet_onbalans_eur"] = _tennet_onbalans
            result["day_ahead_eur"]       = _day_ahead
            result["tennet_up_ct"]        = round(_up * 100, 2)
            result["tennet_dn_ct"]        = round(_dn * 100, 2)

        return result
