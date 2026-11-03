"""Фикстуры и построители тестовых ZIP-архивов AquaBit для юнит-тестов Этапов 0–2."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest


def make_manifest_dict(
    *,
    calc_status: str = "performed",
    converged: bool | None = True,
    pumps: int = 1,
    reservoirs: int = 1,
    valves: int = 0,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "export_id": "exp-2026-10-30-0001",
        "created_at": "2026-10-30T10:00:00+05:00",
        "aquabit_version": "4.2.1",
        "model": {"id": "M-Tenino", "name": "Тенино", "revision": "r12"},
        "scenario": {"id": "S-01", "name": "Суточный максимум", "revision": "r03"},
        "calculation": {
            "id": "CALC-001",
            "status": calc_status,
            "method_headloss": "hazen_williams",
            "solver": "epanet_aquabit",
            "tolerance": 1e-6,
            "max_iterations": 100,
            "converged": converged,
            "convergence_iterations": 12 if converged else None,
        },
        "period": {
            "start": "2026-10-30T00:00:00+05:00",
            "end": "2026-10-31T00:00:00+05:00",
            "step_seconds": 3600,
            "n_steps": 24,
            "timezone": "Asia/Tashkent",
        },
        "units": {
            "head": "m",
            "flow": "m3_h",
            "pressure": "bar",
            "velocity": "m_s",
            "length": "m",
            "diameter": "mm",
        },
        "counts": {
            "nodes": 3,
            "pipes": 2,
            "pumps": pumps,
            "reservoirs": reservoirs,
            "valves": valves,
            "sources": 1,
        },
        "missing_data_summary": {
            "nodes_without_demand_pct": 33.3,
            "pumps_without_curve": 0,
        },
    }
    if overrides:
        data.update(overrides)
    return data


def build_valid_files_map(*, with_results: bool = True) -> dict[str, bytes]:
    """Возвращает эталонный набор файлов ZIP-архива (§2) для тестов."""
    manifest = make_manifest_dict(
        calc_status="performed" if with_results else "not_performed",
        converged=True if with_results else None,
    )
    calc_h1 = "42.5" if with_results else ""
    calc_h2 = "36.2" if with_results else ""
    calc_h3 = "31.0" if with_results else ""

    files: dict[str, str] = {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2),
        "nodes.csv": (
            "id,name,elevation_m,required_pressure_m,calculated_head_m\n"
            f"001,Узел-Вход,10.0,20.0,{calc_h1}\n"
            f"002,XY4973,12.5,20.0,{calc_h2}\n"
            f"N_003,Конечный-тупик,15.0,,{calc_h3}\n"
        ),
        "pipes.csv": (
            "id,name,start_node_id,end_node_id,length_m,diameter_mm,roughness\n"
            "P_01,Водовод-1,SRC_01,001,450.0,300,130\n"
            "P_02,Участок-2,002,N_003,620.5,200,120\n"
        ),
        "sources.csv": (
            "id,name,head_m,flow_m3_h\n"
            f"SRC_01,ВЗУ-1,45.0,{'680.0' if with_results else '0'}\n"
        ),
        "reservoirs.csv": (
            "id,name,elevation_m,level_m,min_level_m,max_level_m\n"
            "RES_01,РЧВ-1,25.0,4.2,1.5,6.0\n"
        ),
        "pumps.csv": (
            "id,name,start_node_id,end_node_id,curve_id\n"
            "PUMP_36,НС-N36,001,002,QH_36\n"
        ),
        "pump_curves.csv": (
            "pump_id,curve_id,flow_m3_h,head_m\n"
            "PUMP_36,QH_36,0.0,48.0\n"
            "PUMP_36,QH_36,400.0,40.0\n"
            "PUMP_36,QH_36,800.0,24.0\n"
        ),
        "demands.csv": (
            "node_id,base_demand_m3_h,curve_id\n"
            "002,120.0,PAT_RESIDENTIAL\n"
            "N_003,0,PAT_RESIDENTIAL\n"
        ),
        "irregularity_curves.csv": (
            "curve_id,step_index,multiplier\n"
            "PAT_RESIDENTIAL,0,0.65\n"
            "PAT_RESIDENTIAL,1,0.55\n"
            "PAT_RESIDENTIAL,2,1.35\n"
        ),
    }

    if with_results:
        files["timeseries/node_pressure.csv"] = (
            "id,time_iso8601,head_m\n"
            "001,2026-10-30T00:00:00+05:00,42.5\n"
            "002,2026-10-30T00:00:00+05:00,36.2\n"
            "N_003,2026-10-30T00:00:00+05:00,31.0\n"
        )
        files["timeseries/pump_state.csv"] = (
            "id,time_iso8601,flow_m3_h,head_m,state\n"
            "PUMP_36,2026-10-30T00:00:00+05:00,670.0,29.0,out_of_working_zone\n"
        )

    return {k: v.encode("utf-8") for k, v in files.items()}


def write_zip_from_map(target_zip: Path, files_map: dict[str, bytes]) -> Path:
    target_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files_map.items():
            zf.writestr(rel_path, content)
    return target_zip


@pytest.fixture()
def valid_results_zip(tmp_path: Path) -> Path:
    return write_zip_from_map(
        tmp_path / "valid_results.zip", build_valid_files_map(with_results=True)
    )


@pytest.fixture()
def valid_no_results_zip(tmp_path: Path) -> Path:
    return write_zip_from_map(
        tmp_path / "valid_no_results.zip", build_valid_files_map(with_results=False)
    )
