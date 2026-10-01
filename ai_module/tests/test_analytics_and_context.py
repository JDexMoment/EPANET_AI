"""Tests for the deterministic analytics engine and context builder."""

import pytest

from ai_module.analytics.engineering_engine import EngineeringAnalyticsEngine
from ai_module.config.settings import DATA_DIR
from ai_module.context.context_builder import ContextBuilder
from ai_module.engine_adapter.ctypes_epanet import EpanetEngineAdapter

DISTRICT_INP = DATA_DIR / "raw_networks" / "city_district_si.inp"
UPGRADED_INP = DATA_DIR / "raw_networks" / "city_district_upgraded.inp"


@pytest.fixture(scope="module")
def sim():
    adapter = EpanetEngineAdapter()
    return adapter.run_simulation(str(DISTRICT_INP), target_period=12)


def test_kpi_computation(sim):
    engine = EngineeringAnalyticsEngine()
    res = engine.analyze(sim)
    kpi = res["kpi"]
    assert kpi.total_demand_lps > 0
    assert kpi.max_velocity_mps > 0
    assert kpi.alerts_count >= 1


def test_alerts_are_sorted_critical_first(sim):
    engine = EngineeringAnalyticsEngine()
    res = engine.analyze(sim)
    severities = [a.severity for a in res["alerts"]]
    rank = {"critical": 0, "warning": 1, "info": 2}
    assert severities == sorted(severities, key=lambda s: rank[s])


def test_focus_object_defaults_to_top_alert(sim):
    engine = EngineeringAnalyticsEngine()
    res = engine.analyze(sim)
    assert res["focus_object_id"] == res["alerts"][0].object


def test_neighborhood_traces_actual_flow_direction(sim):
    engine = EngineeringAnalyticsEngine()
    res = engine.analyze(sim, selected_id="J-104")
    nb = res["topological_neighborhood"]
    assert nb["focus_object"] == "J-104"
    assert len(nb["connected_links"]) >= 1
    for c in nb["connected_links"]:
        assert c["actual_flow_from"] != c["actual_flow_to"]


def test_viewport_filtering(sim):
    engine = EngineeringAnalyticsEngine()
    res = engine.analyze(sim, visible_nodes=["J-101", "J-102"], visible_links=["P-101", "P-102"])
    vp = res["viewport_summary"]
    assert vp["is_zoomed_subregion"] is True
    assert vp["visible_nodes_count"] == 2
    assert vp["visible_links_count"] == 2


def test_context_builder_produces_valid_payload():
    cb = ContextBuilder()
    payload, _sim, _an = cb.build_context(
        inp_file=str(DISTRICT_INP),
        mode="find_problems",
        selected_id="J-104",
        target_period=12,
    )
    assert payload.selection.id == "J-104"
    assert payload.kpi.alerts_count >= 1
    assert len(payload.applicable_rules) >= 1
    assert payload.analysis.active_time_h == pytest.approx(12.0, abs=0.1)


def test_scenario_comparison():
    cb = ContextBuilder()
    payload, _sim, _an = cb.build_context(
        inp_file=str(DISTRICT_INP),
        mode="compare_scenarios",
        compare_inp_file=str(UPGRADED_INP),
        target_period=12,
    )
    sc = payload.scenario_comparison
    assert sc is not None
    assert len(sc["modified_parameters"]) >= 2  # P-103 & P-104 diameter/roughness changed
    # Upgrading P-104 must improve J-104 pressure
    assert sc["kpi_deltas"]["min_pressure_delta_m"] > 0
