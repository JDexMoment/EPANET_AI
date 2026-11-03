"""Юнит-тесты Этапа 1 — Ingestion: распаковка ZIP, запрет автотипизации, raw_snapshot и manifest_out.json."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from aquabit_ai.config import CheckCode, ManifestOutSchema
from aquabit_ai.ingest import build_manifest_out, ingest_zip_archive, write_manifest_out
from tests.conftest import build_valid_files_map, write_zip_from_map


def test_ingest_preserves_raw_strings_leading_zeroes_and_empty_vs_zero(
    valid_results_zip: Path, tmp_path: Path
) -> None:
    bundle = ingest_zip_archive(valid_results_zip, run_id="run-test-01")
    assert not bundle.has_fatal_ingestion_error
    assert bundle.manifest is not None
    assert bundle.manifest.model.name == "Тенино"

    nodes_df = bundle.tables["nodes.csv"].dataframe
    assert nodes_df is not None
    # Ведущие нули сохраняются строго как строка ("001", "002"), а не 1, 2 (§1.7)
    assert nodes_df["id"].tolist() == ["001", "002", "N_003"]
    # Пустое значение остаётся пустой строкой "" (без превращения в NaN или 0.0 на Этапе 1)
    assert nodes_df["required_pressure_m"].tolist() == ["20.0", "20.0", ""]

    demands_df = bundle.tables["demands.csv"].dataframe
    assert demands_df is not None
    # Строковый ноль "0" сохранён без потери
    assert demands_df["base_demand_m3_h"].tolist() == ["120.0", "0"]

    # Проверка записи и валидности manifest_out.json (§4, Этап 1.6)
    mout = build_manifest_out(bundle)
    out_file = write_manifest_out(mout, tmp_path / "out")
    reloaded = ManifestOutSchema.model_validate_json(out_file.read_text(encoding="utf-8"))
    assert reloaded.run_id == "run-test-01"
    nodes_snap = next(s for s in reloaded.raw_snapshot if s.relative_path == "nodes.csv")
    assert nodes_snap.rows == 3
    assert nodes_snap.columns == 5
    assert len(nodes_snap.sha256) == 64


def test_ingest_does_not_rename_raw_columns_and_handles_utf8_bom(tmp_path: Path) -> None:
    files = build_valid_files_map(with_results=False)
    # Русские заголовки + UTF-8 BOM
    russian_nodes = (
        "\ufeffID,Наименование,Отметка в метрах,Требуемый напор в метрах\n"
        "0007,Узел-7,14.2,\n"
    ).encode("utf-8")
    files["nodes.csv"] = russian_nodes
    zip_path = write_zip_from_map(tmp_path / "bom_export.zip", files)

    bundle = ingest_zip_archive(zip_path)
    nodes_table = bundle.tables["nodes.csv"]
    assert nodes_table.has_bom is True
    assert nodes_table.detected_encoding == "utf-8-sig"
    assert nodes_table.dataframe is not None
    # Имена колонок на Этапе 1 НЕ нормализуются (§4, Этап 1: запрещено нормализовать имена колонок)
    assert list(nodes_table.dataframe.columns) == [
        "ID",
        "Наименование",
        "Отметка в метрах",
        "Требуемый напор в метрах",
    ]
    assert nodes_table.dataframe["ID"].tolist() == ["0007"]


def test_ingest_unwraps_single_top_level_directory(tmp_path: Path) -> None:
    base_files = build_valid_files_map(with_results=True)
    wrapped = {f"tenino_export_2026/{k}": v for k, v in base_files.items()}
    wrapped["__MACOSX/.DS_Store"] = b"junk"
    zip_path = write_zip_from_map(tmp_path / "wrapped.zip", wrapped)

    bundle = ingest_zip_archive(zip_path)
    assert not bundle.has_fatal_ingestion_error
    assert "nodes.csv" in bundle.tables
    assert "timeseries/node_pressure.csv" in bundle.tables


def test_ingest_missing_mandatory_and_conditional_files(tmp_path: Path) -> None:
    files = build_valid_files_map(with_results=True)
    del files["pipes.csv"]
    del files["pump_curves.csv"]  # обязателен, т.к. manifest.counts.pumps == 1
    zip_path = write_zip_from_map(tmp_path / "missing.zip", files)

    bundle = ingest_zip_archive(zip_path)
    assert bundle.has_fatal_ingestion_error
    missing_issue = next(i for i in bundle.ingestion_issues if i.code == CheckCode.MISSING_FILE)
    missing_names = {ex["file"] for ex in missing_issue.examples}
    assert "pipes.csv" in missing_names
    assert "pump_curves.csv" in missing_names


def test_ingest_detects_bad_zip_and_unsafe_paths_and_encrypted_entries(tmp_path: Path) -> None:
    # 1. Не-ZIP файл
    not_a_zip = tmp_path / "broken.zip"
    not_a_zip.write_bytes(b"NOT A ZIP ARCHIVE")
    b1 = ingest_zip_archive(not_a_zip)
    assert b1.ingestion_issues[0].code == CheckCode.INVALID_ZIP

    # 2. Path traversal (Zip Slip)
    slip_zip = tmp_path / "slip.zip"
    with zipfile.ZipFile(slip_zip, "w") as zf:
        zf.writestr("../escape.csv", "id\n1\n")
    b2 = ingest_zip_archive(slip_zip)
    assert b2.ingestion_issues[0].code == CheckCode.UNSAFE_ZIP_PATH

    # 3. Зашифрованный член архива (бит 0 в General Purpose Bit Flag локального и центрального заголовка ZIP)
    enc_zip = tmp_path / "encrypted.zip"
    with zipfile.ZipFile(enc_zip, "w") as zf:
        zf.writestr("manifest.json", b"{}")
    raw_zip = bytearray(enc_zip.read_bytes())
    # Local file header signature PK\x03\x04 -> flag_bits по смещению +6
    lfh_pos = raw_zip.find(b"PK\x03\x04")
    raw_zip[lfh_pos + 6] |= 0x01
    # Central directory header signature PK\x01\x02 -> flag_bits по смещению +8
    cdh_pos = raw_zip.find(b"PK\x01\x02")
    raw_zip[cdh_pos + 8] |= 0x01
    enc_zip.write_bytes(bytes(raw_zip))
    b3 = ingest_zip_archive(enc_zip)
    assert b3.ingestion_issues[0].code == CheckCode.ENCRYPTED_ZIP

    # 3b. Несуществующий файл архива
    b_missing_path = ingest_zip_archive(tmp_path / "does_not_exist.zip")
    assert b_missing_path.ingestion_issues[0].code == CheckCode.INVALID_ZIP

    # 4. Битый manifest.json
    files = build_valid_files_map(with_results=False)
    files["manifest.json"] = json.dumps({"schema_version": "1.0"}).encode("utf-8")
    bad_manifest_zip = write_zip_from_map(tmp_path / "bad_manifest.zip", files)
    b4 = ingest_zip_archive(bad_manifest_zip)
    assert any(i.code == CheckCode.MANIFEST_INVALID for i in b4.ingestion_issues)
