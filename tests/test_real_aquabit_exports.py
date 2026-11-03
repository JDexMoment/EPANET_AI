"""Интеграционные тесты на 4 реальных выгрузках AquaBit из tests/fixtures/real/."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from aquabit_ai.cli import app
from aquabit_ai.config import CheckCode
from aquabit_ai.ingest import ingest_legacy_analysis_csv, inspect_aquabit_source
from aquabit_ai.validate import run_validation

REAL_DIR = Path(__file__).parent / "fixtures" / "real"
runner = CliRunner()


@pytest.mark.skipif(
    not (REAL_DIR / "темино анализ 9_25.csv").is_file(),
    reason="Реальная фикстура 'темино анализ 9_25.csv' отсутствует",
)
def test_real_temino_full_stage1_to_stage3_pipeline(tmp_path: Path) -> None:
    temino_csv = REAL_DIR / "темино анализ 9_25.csv"

    # 1. Все 100% реальных заголовков сопоставляются в field_aliases.yaml без эвристик
    inspected = inspect_aquabit_source(temino_csv)
    assert inspected["source_type"] == "legacy_multisection_csv"
    for f_entry in inspected["csv_files"]:
        assert f_entry["unmapped_headers"] == [], f"Несопоставленный заголовок в {f_entry['file']}"

    # 2. Сквозной CLI прогон Этапов 1 -> 2 -> 3 в режиме --legacy-compat
    out_dir = tmp_path / "temino_out"
    res = runner.invoke(
        app,
        [
            "preprocess",
            str(temino_csv),
            "--out",
            str(out_dir),
            "--legacy-compat",
            "--run-id",
            "run-real-temino-01",
        ],
    )
    assert res.exit_code == 0, res.output
    summary = json.loads(res.stdout)
    assert summary["status"] == "ok"
    assert summary["effective_mode"] == "results"
    # 530 узлов + 561 труба + 21 насос + 3 клапана + 1 источник = 1116 сетевых сущностей
    assert summary["entities_registered"] == 1116

    # Проверяем сохранённые Parquet-таблицы и точность различения null vs 0.0
    nodes_pq = pq.read_table(out_dir / "normalized" / "nodes.parquet")
    assert nodes_pq.num_rows == 530
    # В Темино у 316 узлов Требуемое давление пустое -> null, а у 214 задано числом;
    # при этом Рассчитанное Потребление = 0.00 у 329 узлов -> строго 0.0 (НЕ null!)
    q_report = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert q_report["nodes.csv"]["nulls_by_field"]["required_pressure_m"] == 316
    assert q_report["nodes.csv"]["nulls_by_field"]["calculated_demand_m3_h"] == 0
    assert q_report["nodes.csv"]["zeros_by_field"]["calculated_demand_m3_h"] > 300

    # Проверяем реестр сущностей (§3.6): XY4973, P2486, N36 присутствуют как строковые ключи
    ent_reg = json.loads((out_dir / "entity_registry.json").read_text(encoding="utf-8"))
    assert ent_reg["XY4973"]["type"] == "node"
    assert ent_reg["P2486"]["type"] == "pipe"
    assert ent_reg["N36"]["type"] == "pump"

    # Инспекция всей папки real/ также отрабатывает без ошибок
    dir_inspected = inspect_aquabit_source(REAL_DIR)
    assert len(dir_inspected["csv_files"]) > 10


@pytest.mark.parametrize(
    "filename",
    [
        "куляб анализ 7_55.csv",
        "куляб анализ 18_43.csv",
        "модель сетей анализ 5_01.csv",
    ],
)
def test_real_kulyab_and_network_models_produce_fatal_diagnostic_html(
    filename: str, tmp_path: Path
) -> None:
    csv_path = REAL_DIR / filename
    if not csv_path.is_file():
        pytest.skip(f"Реальная фикстура '{filename}' отсутствует")

    bundle = ingest_legacy_analysis_csv(csv_path, run_id=f"run-{csv_path.stem}")
    out_dir = tmp_path / csv_path.stem
    outcome = run_validation(bundle, strict=False, output_dir=out_dir)

    # В этих реальных моделях есть пустые названия узлов "", дубли труб и ссылки на невыгруженные РЧВ
    assert outcome.report.status == "fatal"
    codes = {c.code for c in outcome.report.checks}
    assert CheckCode.DUPLICATE_ID in codes
    assert CheckCode.ORPHAN_REFERENCE in codes
    assert outcome.fatal_html_path is not None and outcome.fatal_html_path.is_file()
