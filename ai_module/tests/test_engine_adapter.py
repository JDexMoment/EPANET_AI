"""Tests for the EPANET 2.2 C-engine ctypes adapter."""

from pathlib import Path

import pytest

from ai_module.config.settings import DATA_DIR
from ai_module.engine_adapter.ctypes_epanet import EpanetEngineAdapter

TUTORIAL_INP = DATA_DIR / "raw_networks" / "tutorial.inp"
DISTRICT_INP = DATA_DIR / "raw_networks" / "city_district_si.inp"


@pytest.fixture(scope="module")
def adapter() -> EpanetEngineAdapter:
    return EpanetEngineAdapter()


def test_tutorial_simulation_runs(adapter):
    res = adapter.run_simulation(str(TUTORIAL_INP), target_period=0)
    assert res["analysis"]["status"].startswith("converged")
    assert res["network_summary"]["junctions"] == 5
    assert res["network_summary"]["pumps"] == 1
    assert res["analysis"]["duration_h"] == pytest.approx(24.0, abs=0.1)
    assert len(res["all_snapshots"]) > 1


def test_units_are_normalized_to_si(adapter):
    res = adapter.run_simulation(str(TUTORIAL_INP), target_period=0)
    assert res["project"]["unit_system_native"] == "US"
    assert "SI" in res["project"]["normalized_units"]
    node = res["active_snapshot"]["nodes"]["3"]
    # Node 3 elevation is 710 ft = 216.4 m
    assert node["head_m"] == pytest.approx(268.123, abs=0.5)
    # 51.701 m pressure derived from psi
    assert node["pressure_m"] == pytest.approx(51.701, abs=0.5)


def test_district_network_has_negative_pressure_bottleneck(adapter):
    res = adapter.run_simulation(str(DISTRICT_INP), target_period=12)
    j104 = res["active_snapshot"]["nodes"]["J-104"]
    assert j104["pressure_m"] < 0.0
    p104 = res["active_snapshot"]["links"]["P-104"]
    assert p104["velocity_mps"] > 1.0
    assert p104["headloss_m_per_km"] > 5.0


def test_coordinates_are_available(adapter):
    res = adapter.run_simulation(str(DISTRICT_INP), target_period=0)
    nodes = {n["id"]: n for n in res["topology"]["nodes"]}
    assert nodes["R-1"]["x"] == pytest.approx(100.0)
    assert nodes["J-104"]["x"] == pytest.approx(1050.0)


def test_missing_file_raises(adapter):
    with pytest.raises(FileNotFoundError):
        adapter.run_simulation("/nonexistent/path/model.inp")
