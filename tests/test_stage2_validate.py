"""Юнит-тесты Этапа 2 — Validation: проверка всех кодов ошибок чек-листа (§4, Этап 2)."""

from __future__ import annotations

from pathlib import Path

from aquabit_ai.config import CheckCode
from aquabit_ai.ingest import ingest_zip_archive
from aquabit_ai.validate import run_validation
from tests.conftest import build_valid_files_map, write_zip_from_map


def test_validate_clean_results_and_no_results_archives(
    valid_results_zip: Path,
    valid_no_results_zip: Path,
) -> None:
    res_outcome = run_validation(ingest_zip_archive(valid_results_zip))
    assert res_outcome.report.status == "ok"
    assert res_outcome.report.effective_mode == "results"
    assert res_outcome.report.checks == []

    no_res_outcome = run_validation(ingest_zip_archive(valid_no_results_zip))
    assert no_res_outcome.report.status == "ok"
    assert no_res_outcome.report.effective_mode == "no_results"
    assert no_res_outcome.report.checks == []


def test_validate_encoding_error_strict_vs_legacy_compat(tmp_path: Path) -> None:
    files = build_valid_files_map(with_results=False)
    # Кириллица в Windows-1251
    cp1251_nodes = (
        "id,name,elevation_m\n"
        "001,Узел-Кириллица,10.0\n"
        "002,XY4973,12.5\n"
        "N_003,Тупик,15.0\n"
    ).encode("cp1251")
    files["nodes.csv"] = cp1251_nodes
    zip_path = write_zip_from_map(tmp_path / "cp1251.zip", files)

    bundle = ingest_zip_archive(zip_path)
    strict_outcome = run_validation(bundle, strict=True)
    assert strict_outcome.report.status == "fatal"
    assert any(
        c.code == CheckCode.ENCODING_ERROR and c.severity == "fatal"
        for c in strict_outcome.report.checks
    )

    compat_outcome = run_validation(bundle, strict=False)
    assert compat_outcome.report.status == "warning"
    assert any(
        c.code == CheckCode.ENCODING_ERROR and c.severity == "warning"
        for c in compat_outcome.report.checks
    )


def test_validate_delimiter_mismatch_tab_tsv(tmp_path: Path) -> None:
    files = build_valid_files_map(with_results=False)
    files["sources.csv"] = b"id\tname\thead_m\tflow_m3_h\nSRC_01\tVZU\t45.0\t0\n"
    zip_path = write_zip_from_map(tmp_path / "tab_delim.zip", files)

    bundle = ingest_zip_archive(zip_path)
    outcome = run_validation(bundle, strict=True)
    assert outcome.report.status == "fatal"
    delim_check = next(c for c in outcome.report.checks if c.code == CheckCode.DELIMITER_MISMATCH)
    assert delim_check.severity == "fatal"
    assert delim_check.developer_hint is not None


def test_validate_schema_mismatch_and_unit_suffix_warning(tmp_path: Path) -> None:
    # 1. Отсутствие обязательной колонки elevation_m -> SCHEMA_MISMATCH (fatal)
    files_bad = build_valid_files_map(with_results=False)
    files_bad["nodes.csv"] = b"id,name\n001,A\n002,B\nN_003,C\n"
    z_bad = write_zip_from_map(tmp_path / "schema_bad.zip", files_bad)
    out_bad = run_validation(ingest_zip_archive(z_bad))
    assert out_bad.report.status == "fatal"
    assert any(c.code == CheckCode.SCHEMA_MISMATCH for c in out_bad.report.checks)

    # 2. Русские заголовки из field_aliases.yaml без суффикса _m -> UNIT_SUFFIX_MISSING (warning)
    files_warn = build_valid_files_map(with_results=False)
    files_warn["sources.csv"] = "ID,Наименование,Напор в метрах\nSRC_01,ВЗУ-1,45.0\n".encode(
        "utf-8"
    )
    z_warn = write_zip_from_map(tmp_path / "unit_warn.zip", files_warn)
    out_warn = run_validation(ingest_zip_archive(z_warn))
    assert out_warn.report.status == "warning"
    assert any(
        c.code == CheckCode.UNIT_SUFFIX_MISSING and c.severity == "warning"
        for c in out_warn.report.checks
    )


def test_validate_duplicate_id_and_string_id_distinction(tmp_path: Path) -> None:
    # "01" и "1" — разные строковые ID (§1.7) -> не должны считаться дублями
    files_distinct = build_valid_files_map(with_results=False)
    files_distinct["nodes.csv"] = (
        "id,elevation_m\n001,10.0\n002,12.0\nN_003,15.0\n01,16.0\n1,17.0\n"
    ).encode("utf-8")
    z_ok = write_zip_from_map(tmp_path / "distinct_str_ids.zip", files_distinct)
    out_ok = run_validation(ingest_zip_archive(z_ok))
    assert out_ok.report.status == "ok"

    # Реальный дубль ID в таблице -> DUPLICATE_ID (fatal)
    files_dup = build_valid_files_map(with_results=False)
    files_dup["nodes.csv"] = "id,elevation_m\n001,10.0\n001,11.0\n002,12.0\nN_003,15.0\n".encode(
        "utf-8"
    )
    z_dup = write_zip_from_map(tmp_path / "dup_ids.zip", files_dup)
    out_dup = run_validation(ingest_zip_archive(z_dup))
    assert out_dup.report.status == "fatal"
    assert any(c.code == CheckCode.DUPLICATE_ID for c in out_dup.report.checks)


def test_validate_duplicate_curve_id_including_legacy_tenino_colon_bug(tmp_path: Path) -> None:
    files = build_valid_files_map(with_results=False)
    # Имитация старого бага модели «Тенино» с не-уникальным ID "1:" (§2)
    files["irregularity_curves.csv"] = (
        "curve_id,step_index,multiplier\n1:,0,0.8\n1:,0,1.1\n"
    ).encode("utf-8")
    files["demands.csv"] = "node_id,base_demand_m3_h,curve_id\n002,120.0,1:\n".encode("utf-8")
    z_curve = write_zip_from_map(tmp_path / "bad_curves.zip", files)

    outcome = run_validation(ingest_zip_archive(z_curve))
    assert outcome.report.status == "fatal"
    curve_check = next(c for c in outcome.report.checks if c.code == CheckCode.DUPLICATE_CURVE_ID)
    assert curve_check.count >= 2


def test_validate_orphan_reference_and_incomplete_pump_curve(tmp_path: Path) -> None:
    files = build_valid_files_map(with_results=True)
    # Труба ссылается на несуществующий узел N_GHOST
    files["pipes.csv"] = (
        "id,start_node_id,end_node_id,length_m,diameter_mm\n"
        "P_01,SRC_01,001,450.0,300\n"
        "P_02,002,N_GHOST,620.5,200\n"
    ).encode("utf-8")
    # Кривая насоса содержит только 2 точки (< 3)
    files["pump_curves.csv"] = (
        "pump_id,flow_m3_h,head_m\nPUMP_36,0.0,48.0\nPUMP_36,400.0,40.0\n"
    ).encode("utf-8")
    z_path = write_zip_from_map(tmp_path / "orphan_and_pump.zip", files)

    outcome = run_validation(ingest_zip_archive(z_path))
    assert outcome.report.status == "fatal"
    codes = {c.code for c in outcome.report.checks}
    assert CheckCode.ORPHAN_REFERENCE in codes
    assert CheckCode.PUMP_CURVE_INCOMPLETE in codes
    assert outcome.report.blocked_pump_analysis_ids == ["PUMP_36"]


def test_validate_mode_switching_and_results_in_no_results_warning(
    valid_results_zip: Path,
    valid_no_results_zip: Path,
) -> None:
    # 1. Запрошен mode="results" на модели без напоров (как «Тенино» без расчёта) ->
    #    NO_RESULTS_BUT_MODE_RESULTS (error) и автоматическое переключение в no_results!
    switched = run_validation(
        ingest_zip_archive(valid_no_results_zip),
        requested_mode="results",
    )
    assert switched.report.status == "warning"
    assert switched.report.requested_mode == "results"
    assert switched.report.effective_mode == "no_results"
    assert switched.report.mode_switched is True
    assert any(
        c.code == CheckCode.NO_RESULTS_BUT_MODE_RESULTS and c.severity == "error"
        for c in switched.report.checks
    )

    # 2. Запрошен mode="no_results", но в выгрузке есть рассчитанные напоры -> warning
    warn_res = run_validation(
        ingest_zip_archive(valid_results_zip),
        requested_mode="no_results",
    )
    assert warn_res.report.status == "warning"
    assert warn_res.report.effective_mode == "no_results"
    assert any(
        c.code == CheckCode.RESULTS_IN_NO_RESULTS_MODE and c.severity == "warning"
        for c in warn_res.report.checks
    )
