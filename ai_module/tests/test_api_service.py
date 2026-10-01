"""End-to-end tests for the local FastAPI AI service."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_module.api.app import app
from ai_module.config.settings import DATA_DIR

DISTRICT_INP = DATA_DIR / "raw_networks" / "city_district_si.inp"
UPGRADED_INP = DATA_DIR / "raw_networks" / "city_district_upgraded.inp"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "epanet-ai"


def test_analyze_what_happens(client):
    r = client.post(
        "/api/v1/analyze",
        json={
            "mode": "what_happens",
            "question": "",
            "inp_file": str(DISTRICT_INP),
            "simulation_state": {"current_period": 12},
            "viewport": {"visible_nodes": ["J-103", "J-104"], "visible_links": ["P-104"]},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"]
    assert body["structured_context"]["kpi"]["min_pressure_node"] == "J-104"
    assert len(body["evidence"]) >= 1
    assert body["backend_used"]


def test_analyze_explain_object(client):
    r = client.post(
        "/api/v1/analyze",
        json={
            "mode": "explain_object",
            "question": "",
            "inp_file": str(DISTRICT_INP),
            "selection": {"type": "junction", "id": "J-104"},
            "simulation_state": {"current_period": 12},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "J-104" in body["answer"]
    assert body["structured_context"]["selection"]["id"] == "J-104"


def test_analyze_generate_report(client, tmp_path):
    r = client.post(
        "/api/v1/analyze",
        json={
            "mode": "generate_report",
            "question": "",
            "inp_file": str(DISTRICT_INP),
            "selection": {"type": "junction", "id": "J-104"},
            "simulation_state": {"current_period": 12},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_path"]
    assert Path(body["report_path"]).exists()


def test_analyze_compare_scenarios(client):
    r = client.post(
        "/api/v1/analyze",
        json={
            "mode": "compare_scenarios",
            "question": "Сравни сценарии до и после реконструкции P-104",
            "inp_file": str(DISTRICT_INP),
            "compare_inp_file": str(UPGRADED_INP),
            "simulation_state": {"current_period": 12},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Сравнение сценариев" in body["answer"]
    assert body["structured_context"]["scenario_comparison"]["kpi_deltas"]["min_pressure_delta_m"] > 0


def test_analyze_missing_file_returns_404(client):
    r = client.post(
        "/api/v1/analyze",
        json={"mode": "what_happens", "question": "", "inp_file": "/nope/missing.inp"},
    )
    assert r.status_code == 404


def test_context_endpoint(client):
    r = client.post(
        "/api/v1/context",
        json={"mode": "find_problems", "question": "", "inp_file": str(DISTRICT_INP),
              "simulation_state": {"current_period": 12}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["structured_context"]["kpi"]["alerts_count"] >= 1
    assert isinstance(body["structured_context"]["alerts"], list)
