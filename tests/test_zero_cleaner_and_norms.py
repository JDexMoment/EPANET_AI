"""Тесты проверки нулевых значений, очистки 4 целевых таблиц и доменных инвариантов (ADR-0008)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from aquabit_ai.cli import app
from aquabit_ai.config import CheckCode
from aquabit_ai.ingest import ingest_any_source
from aquabit_ai.preprocess import run_preprocessing
from aquabit_ai.validate import run_validation
from aquabit_ai.zeros import (
    audit_and_clean_zeros,
    infer_floors_from_required_pressure,
    write_zero_audit_reports,
)
from tests.test_city_folder_and_profiler import build_city_13_csv_folder


RUNNER = CliRunner()


def _read_csv_ids(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return [r[0] for r in rows[1:] if r]


def test_infer_floors_from_required_pressure_norm() -> None:
    """Проверяет отечественную формулу требуемого напора H = 10 + 4*(n - 1) м."""
    assert "0 м" in infer_floors_from_required_pressure(0.0)
    assert "1 эт. (10 м)" == infer_floors_from_required_pressure(10.0)
    assert "2 эт. (14 м)" == infer_floors_from_required_pressure(14.0)
    assert "3 эт. (18 м)" == infer_floors_from_required_pressure(18.0)
    assert "5 эт. (26 м)" == infer_floors_from_required_pressure(26.0)
    assert "9 эт. (42 м)" == infer_floors_from_required_pressure(42.0)
    assert "<10 м" in infer_floors_from_required_pressure(6.0)
    assert "нестанд." in infer_floors_from_required_pressure(15.0)


def test_clean_zeros_in_four_target_tables_preserves_cyclic_pumps_and_nulls(
    tmp_path: Path,
) -> None:
    """Проверяет удаление нулевых строк строго в 4 таблицах и сохранение циклических насосов и null."""
    src_city = build_city_13_csv_folder(
        tmp_path / "data" / "Алматы",
        broken_self_loop_topology=False,
        with_pump_switch_jump=True,  # p1263 полностью 0.00; p1264 имеет 0.00 до R436 и 210.00 с R437!
    )

    # Расширим Узел.csv и Потребители Узел.csv граничными случаями:
    # - c171: Высота=0.00, Требуемое давление=18 (3 этажа) -> ОБЯЗАН ОСТАТЬСЯ (Высота=0 не повод удалять!)
    # - c172: Требуемое давление=14 (2 этажа) -> ОБЯЗАН ОСТАТЬСЯ
    # - c173, c174: Требуемое давление=0 -> УДАЛЯЮТСЯ
    # - c175, c176: Требуемое давление="" (пусто / не указано) -> УДАЛЯЮТСЯ
    (src_city / "Узел.csv").write_text(
        "ID,Высота,Требуемое давление\n"
        "c171,0.00,18\n"
        "c172,118.50,14\n"
        "c173,119.00,0\n"
        "c174,120.10,0.0\n"
        "c175,121.00,\n"
        "c176,121.40,\n",
        encoding="utf-8",
    )

    # В Потребители Узел.csv добавим нулевого абонента (c173, 0.000) и пустого (c174, "")
    (src_city / "Потребители Узел.csv").write_text(
        "ID,Потребление,График\n"
        "c171,120.000,t109\n"
        "c172,15.000,t104\n"
        "c173,0.000,t104\n"
        "c174,,t104\n",
        encoding="utf-8",
    )

    # В Потребление Узел.csv вставим в c176 одну пустую ячейку "" среди 0.00:
    # по Принципу 6 пустая ячейка != 0.0, значит c176 содержит пропуск данных и НЕ считается достоверно 100% нулевой!
    dem_lines = (src_city / "Потребление Узел.csv").read_text(encoding="utf-8").splitlines()
    c176_cells = dem_lines[-1].split(",")
    c176_cells[5] = ""  # null на шаге R4
    dem_lines[-1] = ",".join(c176_cells)
    (src_city / "Потребление Узел.csv").write_text("\n".join(dem_lines) + "\n", encoding="utf-8")

    # 1. Сначала проверим режим только аудита (без удаления файлов)
    audit_only = audit_and_clean_zeros(src_city, perform_clean=False)
    assert audit_only.mode == "audit_only"
    assert audit_only.total_rows_removed == 0
    c_audit = audit_only.cities[0]
    assert c_audit.pruned_transit_nodes_count == 4  # c173..c176
    assert c_audit.pruned_standby_pumps_count == 1  # только p1263 (p1264 циклический!)
    assert c_audit.pruned_zero_consumers_count == 2  # c173 и c174
    assert c_audit.pruned_zero_demand_matrix_rows_count == 3  # c173, c174, c175 (а у c176 есть null!)
    assert c_audit.floor_distribution_by_required_pressure == {
        "3 эт. (18 м)": 1,
        "2 эт. (14 м)": 1,
    }

    # 2. Выполним очистку 4 таблиц в отдельную директорию
    cleaned_dir = tmp_path / "cleaned_almaty"
    clean_rep = audit_and_clean_zeros(
        src_city,
        cleaned_output_root=cleaned_dir,
        perform_clean=True,
    )
    assert clean_rep.mode == "clean_zeros"
    assert clean_rep.total_rows_removed == 4 + 1 + 2 + 3  # 10 нулевых строк суммарно

    # Проверяем каждую из 4 целевых таблиц после очистки:
    assert _read_csv_ids(cleaned_dir / "Узел.csv") == ["c171", "c172"]
    assert _read_csv_ids(cleaned_dir / "Поток Насос.csv") == ["p1264"]
    assert _read_csv_ids(cleaned_dir / "Потребители Узел.csv") == ["c171", "c172"]
    assert _read_csv_ids(cleaned_dir / "Потребление Узел.csv") == ["c171", "c172", "c176"]

    # Проверяем, что остальные 9 таблиц (включая Кривая QH с X=0 и Напор Узел) скопированы без потерь!
    assert len(_read_csv_ids(cleaned_dir / "Кривая QH.csv")) == 4
    assert _read_csv_ids(cleaned_dir / "Напор Узел.csv") == [
        "c171", "c172", "c173", "c174", "c175", "c176"
    ]
    assert (cleaned_dir / "pruned_zero_manifest.json").exists()

    # 3. Самое важное: валидация и препроцессинг очищенной папки проходят БЕЗ ложных ORPHAN_REFERENCE!
    cleaned_bundle = ingest_any_source(cleaned_dir)
    assert cleaned_bundle.pruned_transit_node_ids == {"c173", "c174", "c175", "c176"}
    val_out = run_validation(cleaned_bundle, strict=True)
    codes = {c.code for c in val_out.report.checks}
    assert CheckCode.ORPHAN_REFERENCE not in codes
    assert val_out.report.status == "warning"

    prep_out = run_preprocessing(cleaned_bundle, output_dir=tmp_path / "prep_after_clean")
    assert len(prep_out.wide_artifacts) == 5

    # 4. Проверяем рендеринг отчётов JSON / Markdown / HTML
    rep_paths = write_zero_audit_reports(clean_rep, tmp_path / "zero_reports")
    assert rep_paths["json"].exists()
    assert rep_paths["markdown"].exists()
    assert rep_paths["html"].exists()
    html_txt = rep_paths["html"].read_text(encoding="utf-8")
    assert "Walski" in html_txt
    assert "Поток Насос" in html_txt


def test_cli_check_zeros_and_clean_zeros_in_place_and_prune_node_head(tmp_path: Path) -> None:
    """Проверяет CLI-команды check-zeros и clean-zeros (включая --in-place и --prune-node-head)."""
    data_root = tmp_path / "data"
    build_city_13_csv_folder(data_root / "тенино", broken_self_loop_topology=False)
    build_city_13_csv_folder(data_root / "Орша", broken_self_loop_topology=False)

    chk_res = RUNNER.invoke(
        app,
        ["check-zeros", str(data_root), "-o", str(tmp_path / "chk_out")],
    )
    assert chk_res.exit_code == 0, chk_res.output
    chk_json = json.loads(chk_res.stdout)
    assert chk_json["cities_checked"] == 2
    assert chk_json["cities"][0]["transit_nodes_zero_pressure"] == 4

    cln_res = RUNNER.invoke(
        app,
        [
            "clean-zeros",
            str(data_root),
            "--in-place",
            "--prune-node-head",
            "--report-dir",
            str(tmp_path / "cln_rep"),
        ],
    )
    assert cln_res.exit_code == 0, cln_res.output
    cln_json = json.loads(cln_res.stdout)
    assert cln_json["cities_cleaned"] == 2
    # С флагом --prune-node-head транзитные узлы c173..c176 удалены и из Напор Узел.csv!
    assert _read_csv_ids(data_root / "тенино" / "Напор Узел.csv") == ["c171", "c172"]
    assert _read_csv_ids(data_root / "тенино" / "Узел.csv") == ["c171", "c172"]


def test_domain_validation_id_prefixes_24h_schedules_and_pressure_norms(tmp_path: Path) -> None:
    """Проверяет новые коды валидации ID_PREFIX_MISMATCH, SCHEDULE_STEPS_NOT_24 и ABNORMAL_REQUIRED_PRESSURE."""
    cdir = build_city_13_csv_folder(tmp_path / "модель_проверки", broken_self_loop_topology=False)

    # 1. Нарушаем норматив Требуемое давление: c171 = 6 м (< 10 м для 1 этажа), c172 = 145 м (> 120 м)
    # и добавляем узел с неправильным префиксом n999 вместо c999!
    (cdir / "Узел.csv").write_text(
        "ID,Высота,Требуемое давление\n"
        "c171,122.20,6\n"
        "c172,118.50,145\n"
        "c173,119.00,0\n"
        "c174,120.10,0\n"
        "c175,121.00,0\n"
        "c176,121.40,0\n"
        "n999,120.00,10\n",
        encoding="utf-8",
    )

    # 2. В График потребления.csv оставляем у t104 только 5 строк вместо 24!
    t104_short = "\n".join("t104,1" for _ in range(5))
    t109_ok = "\n".join("t109,1" for _ in range(24))
    (cdir / "График потребления.csv").write_text(
        f"ID,Данные\n{t104_short}\n{t109_ok}\n",
        encoding="utf-8",
    )

    bundle = ingest_any_source(cdir)
    val_out = run_validation(bundle, strict=True)
    by_code = {c.code: c for c in val_out.report.checks}

    assert CheckCode.ID_PREFIX_MISMATCH in by_code
    assert by_code[CheckCode.ID_PREFIX_MISMATCH].count == 1
    assert CheckCode.SCHEDULE_STEPS_NOT_24 in by_code
    assert by_code[CheckCode.SCHEDULE_STEPS_NOT_24].count == 1
    assert CheckCode.ABNORMAL_REQUIRED_PRESSURE in by_code
    assert by_code[CheckCode.ABNORMAL_REQUIRED_PRESSURE].count == 2
