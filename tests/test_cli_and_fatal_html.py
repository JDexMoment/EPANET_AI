"""Интеграционные тесты CLI и генерации автономного диагностического HTML при fatal (§4 Этап 2, §5.7)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from aquabit_ai.cli import app
from tests.conftest import build_valid_files_map, write_zip_from_map

runner = CliRunner()


def test_cli_validate_clean_archive_succeeds(valid_results_zip: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "artifacts_ok"
    result = runner.invoke(
        app,
        ["validate", str(valid_results_zip), "--out", str(out_dir), "--run-id", "run-ok-01"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["effective_mode"] == "results"
    assert payload["diagnostic_html"] is None
    assert (out_dir / "validation_report.json").is_file()
    assert (out_dir / "manifest_out.json").is_file()
    assert not (out_dir / "report.html").exists()


def test_cli_validate_fatal_produces_diagnostic_html_without_traceback(tmp_path: Path) -> None:
    files = build_valid_files_map(with_results=False)
    # Создаём осиротевшую ссылку -> ORPHAN_REFERENCE (fatal)
    files["pipes.csv"] = (
        "id,start_node_id,end_node_id,length_m,diameter_mm\n"
        "P_01,SRC_01,MISSING_NODE_99,450.0,300\n"
    ).encode("utf-8")
    broken_zip = write_zip_from_map(tmp_path / "fatal_orphan.zip", files)
    out_dir = tmp_path / "artifacts_fatal"

    result = runner.invoke(
        app,
        ["validate", str(broken_zip), "--out", str(out_dir), "--run-id", "run-fatal-01"],
    )
    assert result.exit_code == 2
    assert "Traceback" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "fatal"

    html_path = out_dir / "report.html"
    assert html_path.is_file()
    html_text = html_path.read_text(encoding="utf-8")
    assert "ORPHAN_REFERENCE" in html_text
    assert "MISSING_NODE_99" in html_text
    assert "Интерпретация ИИ отключена" in html_text
    assert "Traceback" not in html_text


def test_cli_inspect_headers_on_zip(valid_no_results_zip: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["inspect-headers", str(valid_no_results_zip)])
    assert result.exit_code == 0, result.output
    inspected = json.loads(result.stdout)
    assert inspected["source_type"] == "zip"
    assert inspected["has_manifest"] is True
    nodes_entry = next(f for f in inspected["csv_files"] if f["file"] == "nodes.csv")
    assert nodes_entry["unmapped_headers"] == []

    # Проверка inspect-headers на одиночном CSV с неизвестной колонкой
    single_csv = tmp_path / "custom_nodes.csv"
    single_csv.write_text("ID,Отметка в метрах,НеизвестнаяКолонка\n01,10.5,abc\n", encoding="utf-8")
    res_csv = runner.invoke(app, ["inspect-headers", str(single_csv)])
    assert res_csv.exit_code == 0
    csv_info = json.loads(res_csv.stdout)
    assert csv_info["csv_files"][0]["unmapped_headers"] == ["НеизвестнаяКолонка"]


def test_cli_ingest_command_and_scaffold_imports(valid_results_zip: Path, tmp_path: Path) -> None:
    import aquabit_ai.facts
    import aquabit_ai.jsonl
    import aquabit_ai.llm
    import aquabit_ai.preprocess
    import aquabit_ai.trace

    assert len(aquabit_ai.preprocess.SUBSTAGE_ORDER) == 9
    assert "min" in aquabit_ai.facts.ALLOWED_AGGREGATIONS
    assert aquabit_ai.llm.SYSTEM_PROMPT_VERSION == "v1.0"

    out_dir = tmp_path / "ingest_only"
    res = runner.invoke(app, ["ingest", str(valid_results_zip), "--out", str(out_dir)])
    assert res.exit_code == 0
    assert (out_dir / "manifest_out.json").is_file()

    # Проверка CLI preprocess при LOCALE_DECIMAL_MISMATCH на Этапе 3.2 -> report.html без трейсбека
    files_comma = build_valid_files_map(with_results=False)
    files_comma["nodes.csv"] = (
        "id,name,elevation_m\n001,A,10,5\n"  # не только запятая в числе, проверим через кавычки "10,5"
    ).encode("utf-8")
    files_comma["nodes.csv"] = (
        'id,name,elevation_m\n001,Узел,"10,5"\n002,Узел2,12.0\nN_003,Узел3,15.0\n'
    ).encode("utf-8")
    comma_zip = write_zip_from_map(tmp_path / "comma_num.zip", files_comma)
    out_comma = tmp_path / "out_comma"
    res_prep = runner.invoke(app, ["preprocess", str(comma_zip), "--out", str(out_comma)])
    assert res_prep.exit_code == 2
    assert "Traceback" not in res_prep.stdout
    assert (out_comma / "report.html").is_file()
    assert "LOCALE_DECIMAL_MISMATCH" in (out_comma / "report.html").read_text(encoding="utf-8")
