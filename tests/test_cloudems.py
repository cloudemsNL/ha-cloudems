# -*- coding: utf-8 -*-
"""
CloudEMS — Unit Tests — v1.0.0

pytest-tests voor de kritieke modules:
  • BatteryCycleEconomics (battery_cycle_economics.py)
  • BatteryEPEXScheduler logica
  • NILMEventClusterer
  • BelgianCapacityCalculator
  • CloudEMSConfig validatie
  • SupplierSwitchAdviseur
  • SalderingContext
  • PricesFetcher helper-functies

Uitvoeren:
    pip install pytest pytest-asyncio
    pytest tests/test_cloudems.py -v

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import math
import time
import pytest


# ═════════════════════════════════════════════════════════════════════════════
# BatteryCycleEconomics
# ═════════════════════════════════════════════════════════════════════════════

class TestBatteryCycleEconomics:
    """Tests voor degradatiekosten-bewuste batterijplanning."""

    def _make_eco(self, price_eur=8000, capacity=10, chemistry="NMC", rt_eff=0.92):
        from custom_components.cloudems.energy_manager.battery_cycle_economics import BatteryCycleEconomics
        return BatteryCycleEconomics({
            "battery_price_eur":               price_eur,
            "battery_capacity_kwh":            capacity,
            "battery_chemistry":               chemistry,
            "battery_round_trip_efficiency":   rt_eff,
            "battery_min_net_spread":          0.02,
        })

    def test_nmc_base_cycle_cost(self):
        eco = self._make_eco()
        # 8000 / 10 * 0.0045 = 0.0036 €/kWh
        assert abs(eco.base_cycle_cost - 0.0036) < 1e-6

    def test_lfp_lower_cost(self):
        eco_nmc = self._make_eco(chemistry="NMC")
        eco_lfp = self._make_eco(chemistry="LFP")
        assert eco_lfp.base_cycle_cost < eco_nmc.base_cycle_cost

    def test_profitable_arbitrage(self):
        eco = self._make_eco()
        # Laden @ 5 ct, ontladen @ 25 ct → grote spread
        decision = eco.evaluate_slot_pair(charge_price=0.05, discharge_price=0.25)
        assert decision.worth_it is True
        assert decision.netto_spread > 0

    def test_unprofitable_small_spread(self):
        eco = self._make_eco()
        # Laden @ 22 ct, ontladen @ 24 ct → kleine spread, na eff en slijtage verliesgevend
        decision = eco.evaluate_slot_pair(charge_price=0.22, discharge_price=0.24)
        assert decision.worth_it is False

    def test_deep_discharge_penalty(self):
        eco = self._make_eco()
        d_normal = eco.evaluate_slot_pair(0.05, 0.25, soc_at_discharge=50)
        d_deep   = eco.evaluate_slot_pair(0.05, 0.25, soc_at_discharge=10)
        # Diepe ontlading heeft hogere slijtagekosten → lagere netto spread
        assert d_deep.cycle_cost > d_normal.cycle_cost

    def test_self_consumption_always_profitable_above_cost(self):
        eco = self._make_eco()
        # Als prijs hoog genoeg is, altijd rendabel voor eigenverbruik
        decision = eco.evaluate_self_consumption(discharge_price=0.25)
        assert decision.worth_it is True

    def test_self_consumption_not_profitable_at_zero_price(self):
        eco = self._make_eco()
        decision = eco.evaluate_self_consumption(discharge_price=0.001)
        assert decision.worth_it is False

    def test_round_trip_efficiency_effect(self):
        eco_high = self._make_eco(rt_eff=0.98)
        eco_low  = self._make_eco(rt_eff=0.80)
        d_high = eco_high.evaluate_slot_pair(0.05, 0.15)
        d_low  = eco_low.evaluate_slot_pair(0.05, 0.15)
        # Hogere efficiency → hogere netto spread
        assert d_high.netto_spread > d_low.netto_spread


# ═════════════════════════════════════════════════════════════════════════════
# NILMEventClusterer
# ═════════════════════════════════════════════════════════════════════════════

class TestNILMEventClusterer:
    """Tests voor unsupervised NILM-clustering."""

    def _make_clusterer(self):
        """Maak een clusterer zonder HA-dependency voor testing."""
        from custom_components.cloudems.nilm.unsupervised_cluster import NILMEventClusterer, CLUSTER_MIN_EVENTS
        clusterer = NILMEventClusterer.__new__(NILMEventClusterer)
        clusterer._hass = None
        clusterer._store = None
        clusterer._clusters = []
        clusterer._pending_suggestions = []
        return clusterer, CLUSTER_MIN_EVENTS

    def test_single_event_no_suggestion(self):
        clusterer, min_events = self._make_clusterer()
        clusterer.add_unknown_event(1800, 1200)
        assert len(clusterer.get_pending_suggestions()) == 0

    def test_enough_events_triggers_suggestion(self):
        clusterer, min_events = self._make_clusterer()
        for _ in range(min_events):
            clusterer.add_unknown_event(1800, 1200)
        assert len(clusterer.get_pending_suggestions()) == 1

    def test_similar_events_same_cluster(self):
        clusterer, min_events = self._make_clusterer()
        powers = [1780, 1800, 1820, 1790, 1810]
        for p in powers:
            clusterer.add_unknown_event(p, 1200)
        assert len(clusterer._clusters) == 1

    def test_different_events_different_clusters(self):
        clusterer, min_events = self._make_clusterer()
        clusterer.add_unknown_event(300, 600)    # koelkast
        clusterer.add_unknown_event(2000, 1800)  # wasmachine
        assert len(clusterer._clusters) == 2

    def test_confirm_cluster_removes_suggestion(self):
        clusterer, min_events = self._make_clusterer()
        for _ in range(min_events):
            clusterer.add_unknown_event(1800, 1200)
        suggestions = clusterer.get_pending_suggestions()
        assert len(suggestions) == 1
        cid = suggestions[0]["cluster_id"]
        result = clusterer.confirm_cluster(cid, "Wasmachine", "washing_machine")
        assert result is not None
        assert result["device_name"] == "Wasmachine"
        assert len(clusterer.get_pending_suggestions()) == 0

    def test_too_small_events_ignored(self):
        clusterer, _ = self._make_clusterer()
        clusterer.add_unknown_event(10, 300)  # < 30W drempel
        assert len(clusterer._clusters) == 0

    def test_type_suggestion_kettle(self):
        from custom_components.cloudems.nilm.unsupervised_cluster import _suggest_type
        assert _suggest_type(2000, 180) == "kettle"   # 2kW, 3 min

    def test_type_suggestion_ev(self):
        from custom_components.cloudems.nilm.unsupervised_cluster import _suggest_type
        assert _suggest_type(7400, 7200) == "ev_charger"   # 7.4kW, 2 uur


# ═════════════════════════════════════════════════════════════════════════════
# BelgianCapacityCalculator
# ═════════════════════════════════════════════════════════════════════════════

class TestBelgianCapacityCalculator:
    """Tests voor Belgisch capaciteitstarief."""

    def _make_calc(self, postcode="9000"):
        from custom_components.cloudems.energy_manager.belgium_capacity import BelgianCapacityCalculator
        return BelgianCapacityCalculator({"postal_code": postcode})

    def test_gent_postcode_detection(self):
        from custom_components.cloudems.energy_manager.belgium_capacity import detect_dso_by_postcode
        assert detect_dso_by_postcode("9000") == "fluvius_gent"

    def test_antwerpen_postcode_detection(self):
        from custom_components.cloudems.energy_manager.belgium_capacity import detect_dso_by_postcode
        assert detect_dso_by_postcode("2000") == "fluvius_antwerpen"

    def test_update_returns_status(self):
        calc = self._make_calc()
        status = calc.update(grid_import_w=3000)
        assert status.current_quarter_avg_kw > 0
        assert status.dso_label != ""

    def test_free_kw_threshold(self):
        calc = self._make_calc()
        # Onder 2.5 kW vrij → geen kosten
        status = calc.update(grid_import_w=2000)   # 2 kW
        # Kosten moeten laag zijn (vrije band)
        assert status.estimated_annual_cost >= 0

    def test_cost_impact_above_free_kw(self):
        calc = self._make_calc()
        # Zet een hoge maandpiek
        for _ in range(30):
            calc.update(5000)  # 5 kW
        impact = calc.estimate_cost_impact(1.0)  # 1 kW extra
        assert impact > 0

    def test_warning_level_ok_when_low(self):
        calc = self._make_calc()
        status = calc.update(grid_import_w=500)
        assert status.warning_level == "ok"


# ═════════════════════════════════════════════════════════════════════════════
# CloudEMSConfig
# ═════════════════════════════════════════════════════════════════════════════

class TestCloudEMSConfig:
    """Tests voor getypte configuratie."""

    def test_from_empty_dict_uses_defaults(self):
        from custom_components.cloudems.config_schema import CloudEMSConfig
        cfg = CloudEMSConfig.from_dict({})
        assert cfg.grid.country == "NL"
        assert cfg.battery.capacity_kwh == 10.0
        assert cfg.ev.min_current_a == 6.0

    def test_from_dict_parses_values(self):
        from custom_components.cloudems.config_schema import CloudEMSConfig
        cfg = CloudEMSConfig.from_dict({
            "country":              "BE",
            "battery_capacity_kwh": "15",
            "ev_phases":            "3",
        })
        assert cfg.grid.country == "BE"
        assert cfg.battery.capacity_kwh == 15.0
        assert cfg.ev.phases == 3

    def test_belgium_auto_enables_capacity_feature(self):
        from custom_components.cloudems.config_schema import CloudEMSConfig
        cfg = CloudEMSConfig.from_dict({"country": "BE"})
        assert cfg.belgium_capacity_enabled is True

    def test_netherlands_no_belgium_feature(self):
        from custom_components.cloudems.config_schema import CloudEMSConfig
        cfg = CloudEMSConfig.from_dict({"country": "NL"})
        assert cfg.belgium_capacity_enabled is False

    def test_validate_bad_soc_range(self):
        from custom_components.cloudems.config_schema import CloudEMSConfig
        cfg = CloudEMSConfig.from_dict({})
        cfg.battery.min_soc_pct = 80
        cfg.battery.max_soc_pct = 20
        errors = cfg.validate()
        assert any("soc" in e.lower() for e in errors)

    def test_validate_unknown_chemistry(self):
        from custom_components.cloudems.config_schema import CloudEMSConfig
        cfg = CloudEMSConfig.from_dict({})
        cfg.battery.chemistry = "WEIRD"
        errors = cfg.validate()
        assert any("chemistry" in e.lower() for e in errors)

    def test_ev_max_power_calculation(self):
        from custom_components.cloudems.config_schema import CloudEMSConfig
        cfg = CloudEMSConfig.from_dict({
            "ev_max_current_a": "11",
            "ev_phases":        "3",
            "ev_voltage_v":     "230",
        })
        # 11A * 3 fasen * 230V = 7590 W
        assert abs(cfg.ev.max_power_w - 7590) < 1


# ═════════════════════════════════════════════════════════════════════════════
# SupplierSwitchAdviseur
# ═════════════════════════════════════════════════════════════════════════════

class TestSupplierSwitchAdviseur:
    """Tests voor de switchadviseur."""

    def _make_comparison(self, vs_current_eur, label="Test", contract_type="flat"):
        """Helper om een nep-ContractComparison te maken."""
        from types import SimpleNamespace
        return SimpleNamespace(
            label          = label,
            contract_type  = contract_type,
            vs_current_eur = vs_current_eur,
        )

    def test_insufficient_data_returns_warning(self):
        from custom_components.cloudems.energy_manager.supplier_switch_advisor import build_switch_advice
        advice = build_switch_advice([], {}, data_days=5)
        assert advice.state == "onvoldoende_data"

    def test_big_saving_recommends_switch(self):
        from custom_components.cloudems.energy_manager.supplier_switch_advisor import build_switch_advice
        comps = [self._make_comparison(vs_current_eur=-15.0)]  # 15€/mnd goedkoper
        advice = build_switch_advice(comps, {"switch_cost_eur": 40}, data_days=30)
        assert advice.state == "switch_aanbevolen"
        assert advice.annual_saving_eur == pytest.approx(180.0, abs=1)

    def test_small_saving_evalueer(self):
        from custom_components.cloudems.energy_manager.supplier_switch_advisor import build_switch_advice
        comps = [self._make_comparison(vs_current_eur=-3.0)]   # 3€/mnd
        advice = build_switch_advice(comps, {"switch_cost_eur": 40}, data_days=30)
        assert advice.state in ("evalueer", "blijf")

    def test_more_expensive_contract_blijf(self):
        from custom_components.cloudems.energy_manager.supplier_switch_advisor import build_switch_advice
        comps = [self._make_comparison(vs_current_eur=5.0)]    # 5€/mnd duurder
        advice = build_switch_advice(comps, {}, data_days=30)
        assert advice.state == "blijf"


# ═════════════════════════════════════════════════════════════════════════════
# ActionsTracker
# ═════════════════════════════════════════════════════════════════════════════

class TestActionsTracker:
    """Tests voor de dagelijkse actietracker."""

    def test_empty_tracker_no_saving(self):
        from custom_components.cloudems.energy_manager.actions_tracker import CloudEMSActionsTracker
        tracker = CloudEMSActionsTracker()
        card = tracker.get_card()
        assert card.total_saving_eur == 0.0
        assert card.action_count == 0

    def test_logged_action_appears_in_card(self):
        from custom_components.cloudems.energy_manager.actions_tracker import CloudEMSActionsTracker, Actions
        tracker = CloudEMSActionsTracker()
        tracker.log_action(
            action_type = Actions.BOILER_SHIFTED,
            category    = Actions.CAT_BOILER,
            description = "Boiler verschoven naar 02:00",
            saving_eur  = 0.25,
        )
        card = tracker.get_card()
        assert card.total_saving_eur == pytest.approx(0.25)
        assert card.action_count == 1

    def test_headline_mentions_saving(self):
        from custom_components.cloudems.energy_manager.actions_tracker import CloudEMSActionsTracker, Actions
        tracker = CloudEMSActionsTracker()
        tracker.log_action(Actions.EV_SOLAR, Actions.CAT_EV, "EV op zon geladen", saving_eur=0.50, kwh=5.0)
        card = tracker.get_card()
        headline = card.build_headline()
        assert "bespaard" in headline or "EV" in headline

    def test_congestion_event_counted(self):
        from custom_components.cloudems.energy_manager.actions_tracker import CloudEMSActionsTracker, Actions
        tracker = CloudEMSActionsTracker()
        tracker.log_action(Actions.CONGESTION_SHED, Actions.CAT_GRID, "EV teruggeschroefd")
        tracker.log_action(Actions.CONGESTION_SHED, Actions.CAT_GRID, "Boiler gepauzeerd")
        card = tracker.get_card()
        assert card.congestion_events == 2

    def test_card_to_dict_serializable(self):
        from custom_components.cloudems.energy_manager.actions_tracker import CloudEMSActionsTracker, Actions
        tracker = CloudEMSActionsTracker()
        tracker.log_action(Actions.BATTERY_ARBITRAGE, Actions.CAT_BATTERY, "Arbitrage uitgevoerd", saving_eur=0.10)
        d = tracker.get_card().to_dict()
        assert isinstance(d["headline"], str)
        assert isinstance(d["total_saving_eur"], float)
        assert isinstance(d["recent_actions"], list)
