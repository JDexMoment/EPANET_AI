"""Тесты адаптера папок городов (13 CSV с матрицами R0..R1439) и профилировщика экспорта (ADR-0007)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from typer.testing import CliRunner

from aquabit_ai.cli import app
from aquabit_ai.config import CheckCode
from aquabit_ai.ingest import (
    discover_city_directories,
    ingest_any_source,
    inspect_aquabit_source,
)
from aquabit_ai.preprocess import run_preprocessing
from aquabit_ai.profile import profile_aquabit_export, write_export_profile_artifacts
from aquabit_ai.validate import run_validation


RUNNER = CliRunner()

# Реальные 24 часовых коэффициента кривой t109 из модели «Тенино»
T109_HOURLY = [
    0.8991667, 0.6700833, 0.6133333, 0.5663333, 0.5819167, 0.6639167,
    0.8963333, 1.3656667, 1.1235000, 1.0669167, 0.9961667, 0.9616667,
    0.9465833, 0.9532500, 0.9410833, 0.9631667, 1.0315000, 1.1642500,
    1.3670833, 1.3578333, 1.2416667, 1.0890833, 0.9852500, 0.9230833,
]


def _interp_1440_from_hourly(hourly_24: list[float], scale: float = 1.0, decimals: int = 2) -> list[str]:
    """Генерирует 1 440 минутных точек линейной интерполяцией 24 часовых узлов (как в ядре AquaBit)."""
    knots_x = [h * 60 for h in range(24)] + [1440]
    knots_y = [v * scale for v in hourly_24] + [hourly_24[0] * scale]
    vals = np.interp(np.arange(1440, dtype=np.float64), knots_x, knots_y)
    return [f"{v:.{decimals}f}" for v in vals]


def build_city_13_csv_folder(
    city_dir: Path,
    *,
    broken_self_loop_topology: bool = True,
    with_pump_switch_jump: bool = False,
) -> Path:
    """Создаёт аутентичную папку города из 13 CSV-таблиц по реальному образцу пользователя."""
    city_dir.mkdir(parents=True, exist_ok=True)
    r_headers = ",".join(["ID"] + [f"R{i}" for i in range(1440)])

    # 1. Узел.csv (2 абонентских узла: 1 эт. = 10 м и 2 эт. = 14 м; 4 транзитных узла с Hтреб = 0)
    (city_dir / "Узел.csv").write_text(
        "ID,Высота,Требуемое давление\n"
        "c171,122.20,10\n"
        "c172,118.50,14\n"
        "c173,119.00,0\n"
        "c174,120.10,0\n"
        "c175,121.00,0\n"
        "c176,121.40,0\n",
        encoding="utf-8",
    )

    # 2. Источники.csv
    (city_dir / "Источники.csv").write_text(
        "ID,Расчетный напор\n"
        "e701,150.0\n",
        encoding="utf-8",
    )

    # 3. Труба.csv (в broken-режиме воспроизводим реальный баг e702,c702,c702)
    if broken_self_loop_topology:
        pipes_txt = (
            "ID,Начало,Конец,Диаметр,Длина,Шероховатость,Малые потери\n"
            "e702,c702,c702,100,11.66,45.36,0\n"
            "e703,c703,c703,200,145.0,12.10,0\n"
            "e704,c704,c704,150,85.4,18.00,0\n"
        )
        pumps_txt = (
            "ID,Начало,Конец,Кривая насоса\n"
            "p1263,c1263,c1263,u123\n"
            "p1264,c1264,c1264,u123\n"
        )
        valves_txt = (
            "ID,Начало,Конец,Тип,Настройка\n"
            "v1284,c1284,c1284,V1,53\n"
        )
    else:
        pipes_txt = (
            "ID,Начало,Конец,Диаметр,Длина,Шероховатость,Малые потери\n"
            "e702,e701,c171,100,11.66,45.36,0\n"
            "e703,c171,c172,200,145.0,12.10,0\n"
            "e704,c173,c174,150,85.4,18.00,0\n"
        )
        pumps_txt = (
            "ID,Начало,Конец,Кривая насоса\n"
            "p1263,c172,c173,u123\n"
            "p1264,c174,c175,u123\n"
        )
        valves_txt = (
            "ID,Начало,Конец,Тип,Настройка\n"
            "v1284,c175,c176,V1,53\n"
        )

    (city_dir / "Труба.csv").write_text(pipes_txt, encoding="utf-8")
    (city_dir / "Насос.csv").write_text(pumps_txt, encoding="utf-8")
    (city_dir / "Клапан.csv").write_text(valves_txt, encoding="utf-8")

    # 6. Кривая QH.csv (многострочная кривая u123 с 3 точками + u111 с 1 точкой как в примере пользователя)
    (city_dir / "Кривая QH.csv").write_text(
        "ID,X,Y\n"
        "u111,3600,52\n"
        "u123,0,64\n"
        "u123,1800,54\n"
        "u123,3600,38\n",
        encoding="utf-8",
    )

    # 7. График потребления.csv (по 24 часовые строки на каждый t* ID: t104 и t109)
    t104_rows = "\n".join("t104,1" for _ in range(24))
    t109_rows = "\n".join(f"t109,{m:.7f}" for m in T109_HOURLY)
    (city_dir / "График потребления.csv").write_text(
        f"ID,Данные\n{t104_rows}\n{t109_rows}\n",
        encoding="utf-8",
    )

    # 8. Потребители Узел.csv (только у c171 и c172 есть абоненты; у c171 сразу 2 абонента!)
    (city_dir / "Потребители Узел.csv").write_text(
        "ID,Потребление,График\n"
        "c171,120.000,t109\n"
        "c172,15.000,t104\n",
        encoding="utf-8",
    )

    # 9. Напор Узел.csv (R0..R1439, квазиконстантный 149.96..149.99 у источника + плавный профиль)
    h_c171 = [f"{149.99 - 0.03 * (m - 0.56) / 0.85:.2f}" for m in np.interp(
        np.arange(1440), [h * 60 for h in range(24)] + [1440], T109_HOURLY + [T109_HOURLY[0]]
    )]
    h_c172 = _interp_1440_from_hourly([142.0 - 3.5 * m for m in T109_HOURLY], scale=1.0)
    h_const = ["140.10"] * 1440
    # В c176 намеренно вставим пустую ячейку "" (null) и "NaN" для проверки Принципа 6!
    h_c176 = ["138.50"] * 1440
    h_c176[10] = ""
    h_c176[11] = "NaN"

    (city_dir / "Напор Узел.csv").write_text(
        "\n".join(
            [
                r_headers,
                "c171," + ",".join(h_c171),
                "c172," + ",".join(h_c172),
                "c173," + ",".join(h_const),
                "c174," + ",".join(h_const),
                "c175," + ",".join(h_const),
                "c176," + ",".join(h_c176),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # 10. Потребление Узел.csv (4 из 6 узлов = 66.7% полностью нулевые 0.00; c171 и c172 = базовая × график)
    dem_c171 = _interp_1440_from_hourly(T109_HOURLY, scale=120.0)
    dem_c172 = ["15.00"] * 1440
    zero_1440 = ",".join(["0.00"] * 1440)
    (city_dir / "Потребление Узел.csv").write_text(
        "\n".join(
            [
                r_headers,
                "c171," + ",".join(dem_c171),
                "c172," + ",".join(dem_c172),
                f"c173,{zero_1440}",
                f"c174,{zero_1440}",
                f"c175,{zero_1440}",
                f"c176,{zero_1440}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # 11. Поток Труба.csv (включая отрицательный реверсный поток в e703 и смену знака в e704)
    q_e702 = _interp_1440_from_hourly(T109_HOURLY, scale=1.91)
    q_e703 = _interp_1440_from_hourly([-1.0 * m for m in T109_HOURLY], scale=45.0)
    q_e704 = _interp_1440_from_hourly([m - 1.0 for m in T109_HOURLY], scale=20.0)
    (city_dir / "Поток Труба.csv").write_text(
        "\n".join(
            [
                r_headers,
                "e702," + ",".join(q_e702),
                "e703," + ",".join(q_e703),
                "e704," + ",".join(q_e704),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # 12. Поток Клапан.csv
    q_v1284 = _interp_1440_from_hourly(T109_HOURLY, scale=119.5)
    (city_dir / "Поток Клапан.csv").write_text(
        f"{r_headers}\nv1284,{','.join(q_v1284)}\n",
        encoding="utf-8",
    )

    # 13. Поток Насос.csv (p1263 — резервный насос 0.00 все сутки; p1264 — рабочий или с пуском внутри часа)
    if with_pump_switch_jump:
        p1264_vals = ["0.00"] * 437 + ["320.00"] * (1440 - 437)
    else:
        p1264_vals = ["0.00"] * 1440
    (city_dir / "Поток Насос.csv").write_text(
        f"{r_headers}\np1263,{zero_1440}\np1264,{','.join(p1264_vals)}\n",
        encoding="utf-8",
    )

    return city_dir


def test_city_folder_detects_self_loop_exporter_bug_in_strict_mode(tmp_path: Path) -> None:
    """Строгая валидация обязана поймать баг e702 -> c702,c702 (SELF_LOOP_LINK + ORPHAN_REFERENCE)."""
    tenino_dir = build_city_13_csv_folder(tmp_path / "data" / "тенино", broken_self_loop_topology=True)
    bundle = ingest_any_source(tenino_dir)
    assert len(bundle.tables) == 13
    assert bundle.manifest is not None
    assert bundle.manifest.period.n_steps == 1440
    assert bundle.manifest.period.step_seconds == 60

    out_dir = tmp_path / "val_strict"
    outcome = run_validation(bundle, strict=True, output_dir=out_dir)
    assert outcome.report.status == "fatal"
    codes = {c.code: c for c in outcome.report.checks}

    assert CheckCode.SELF_LOOP_LINK in codes
    assert codes[CheckCode.SELF_LOOP_LINK].severity == "fatal"
    assert codes[CheckCode.SELF_LOOP_LINK].count == 6  # 3 трубы + 2 насоса + 1 клапан
    assert codes[CheckCode.SELF_LOOP_LINK].examples[0]["exporter_own_id_cast_bug"] is True

    assert CheckCode.ORPHAN_REFERENCE in codes
    assert CheckCode.MISSING_ENTITY_NAMES in codes
    assert outcome.fatal_html_path is not None and outcome.fatal_html_path.exists()


def test_city_folder_preprocess_succeeds_on_valid_topology_and_preserves_null_vs_nan(
    tmp_path: Path,
) -> None:
    """На исправленной топологии все 13 таблиц проходят Этапы 1–3 и сохраняют null vs 0.0 vs IEEE NaN в Parquet."""
    almaty_dir = build_city_13_csv_folder(
        tmp_path / "data" / "Алматы", broken_self_loop_topology=False, with_pump_switch_jump=True
    )
    bundle = ingest_any_source(almaty_dir)
    val_out = run_validation(bundle, strict=True)
    assert val_out.report.status == "warning"  # только предупреждения UNIT_SUFFIX_MISSING и MISSING_ENTITY_NAMES
    assert val_out.report.effective_mode == "results"
    assert val_out.report.blocked_pump_analysis_ids == []  # у u123 ровно 3 точки!

    out_dir = tmp_path / "prep_almaty"
    prep = run_preprocessing(bundle, output_dir=out_dir)
    assert len(prep.wide_artifacts) == 5
    assert len(prep.entity_registry) == 13  # 6 узлов + 1 источник + 3 трубы + 2 насоса + 1 клапан

    # Проверяем Zstd Parquet для Напор Узел: c176 содержит ровно 1 Arrow null (R10) и 1 IEEE NaN (R11)!
    head_pq = pq.read_table(out_dir / "normalized" / "wide" / "node_head.parquet")
    assert head_pq.num_rows == 6
    assert head_pq.num_columns == 1441  # id + R0..R1439
    r10_col = head_pq.column("R10").combine_chunks()
    r11_col = head_pq.column("R11").combine_chunks()
    assert r10_col.is_null().to_pylist()[5] is True
    assert r11_col.is_null().to_pylist()[5] is False
    assert np.isnan(r11_col.to_pylist()[5])

    # Проверяем wide_summary/pipe_flow.parquet (знакопеременная труба e704 и реверсная e703)
    pipe_sum_pq = pq.read_table(out_dir / "normalized" / "wide_summary" / "pipe_flow.parquet")
    ids = pipe_sum_pq.column("id").to_pylist()
    neg_steps = pipe_sum_pq.column("negative_steps").to_pylist()
    reversals = pipe_sum_pq.column("sign_changes_count").to_pylist()
    e703_idx = ids.index("e703")
    e704_idx = ids.index("e704")
    assert neg_steps[e703_idx] == 1440
    assert reversals[e703_idx] == 0  # стабильно обратный поток без колебаний направления
    assert reversals[e704_idx] >= 2  # настоящая смена знака потока в течение суток!


def test_cli_allow_broken_topology_and_export_profiler_across_multiple_cities(
    tmp_path: Path,
) -> None:
    """Пакетный профилировщик и CLI --allow-broken-topology работают на каталоге data/ с несколькими городами."""
    data_root = tmp_path / "data"
    build_city_13_csv_folder(data_root / "тенино", broken_self_loop_topology=True)
    build_city_13_csv_folder(data_root / "куляб", broken_self_loop_topology=True, with_pump_switch_jump=True)
    build_city_13_csv_folder(data_root / "Алматы", broken_self_loop_topology=False)

    discovered = discover_city_directories(data_root)
    assert [d.name for d in discovered] == ["Алматы", "куляб", "тенино"]

    # 1. CLI preprocess с флагом --allow-broken-topology проходит на сломанном «тенино»
    prep_res = RUNNER.invoke(
        app,
        [
            "preprocess",
            str(data_root / "тенино"),
            "--allow-broken-topology",
            "-o",
            str(tmp_path / "tenino_prep"),
        ],
    )
    assert prep_res.exit_code == 0, prep_res.output
    prep_json = json.loads(prep_res.stdout)
    assert prep_json["wide_matrices_normalized"] == 5

    # 2. CLI batch-validate проверяет все 3 города сразу
    bval_res = RUNNER.invoke(
        app,
        ["batch-validate", str(data_root), "-o", str(tmp_path / "batch_val")],
    )
    assert bval_res.exit_code == 0, bval_res.output
    bval_json = json.loads(bval_res.stdout)
    assert bval_json["cities_checked"] == 3
    assert bval_json["fatal_count"] == 2  # тенино и куляб (баг Начало==Конец)
    assert bval_json["warning_count"] == 1  # Алматы

    # 3. CLI profile-export строит полный отчёт информативности и оптимизации по всем 3 городам
    prof_out = tmp_path / "profile_report"
    prof_res = RUNNER.invoke(
        app,
        ["profile-export", str(data_root), "-o", str(prof_out)],
    )
    assert prof_res.exit_code == 0, prof_res.output
    assert (prof_out / "export_profile.json").exists()
    assert (prof_out / "export_optimization_report.md").exists()
    assert (prof_out / "export_optimization_report.html").exists()

    profile = profile_aquabit_export(data_root)
    assert profile.cities_count == 3
    assert profile.wide_bytes_share_pct > 90.0
    assert profile.savings_hourly_pct > 90.0
    assert profile.savings_compact_v2_pct > 95.0

    # Проверяем доказательство 100% избыточности Потребление Узел.csv и точности часовой интерполяции
    tenino_prof = next(c for c in profile.cities if c.city_name == "тенино")
    assert tenino_prof.exporter_own_id_cast_bug_detected is True
    assert tenino_prof.demand_redundancy.can_drop_node_demand_matrix is True
    assert tenino_prof.demand_redundancy.all_zero_demand_rows_pct > 60.0
    assert (tenino_prof.demand_redundancy.hourly_algebraic_max_diff or 0.0) <= 0.02

    # В «куляб» профилировщик обязан заметить внутричасовое ступенчатое включение насоса p1264 на R437!
    kulyab_prof = next(c for c in profile.cities if c.city_name == "куляб")
    pump_fp = next(f for f in kulyab_prof.files if f.canonical_path == "wide/pump_flow.csv")
    assert pump_fp.abrupt_switch_rows_count == 1


def test_consumption_schedule_variants_and_wide_error_pinpointing(tmp_path: Path) -> None:
    """Проверяет нестандартные записи График потребления.csv, inspect-headers и локализацию ошибок в Rk."""
    cdir = build_city_13_csv_folder(tmp_path / "Орша", broken_self_loop_topology=False)

    # Вариант с несколькими колонками через запятую и пробелами внутри График потребления.csv
    (cdir / "График потребления.csv").write_text(
        "ID,Данные\n"
        "t104,1\n"
        "t109," + ",".join(f"{m:.4f}" for m in T109_HOURLY) + "\n"
        't200,"0.5 1.0 1.5"\n',
        encoding="utf-8-sig",
    )

    insp = inspect_aquabit_source(cdir)
    assert insp["source_type"] == "city_folder"
    assert all(len(f["unmapped_headers"]) == 0 for f in insp["csv_files"])

    bundle = ingest_any_source(cdir)
    val_ok = run_validation(bundle, strict=True)
    assert val_ok.report.status == "warning"

    # Вносим запятую локали "12,5" в широкую матрицу R2 -> пинпоинтер должен точно назвать колонку R2
    (cdir / "Поток Клапан.csv").write_text(
        "ID,R0,R1,R2\nv1284,10.0,11.0,\"12,5\"\n",
        encoding="utf-8",
    )
    bad_bundle = ingest_any_source(cdir)
    bad_val = run_validation(bad_bundle, strict=True)
    assert bad_val.report.status == "fatal"
    schema_chk = next(c for c in bad_val.report.checks if c.code == CheckCode.SCHEMA_MISMATCH)
    assert "LOCALE_DECIMAL_MISMATCH" in schema_chk.examples[0]["detail"]


def test_city_folder_edge_cases_bom_cp1251_ragged_and_missing_mandatory(tmp_path: Path) -> None:
    """Покрывает ветви BOM/cp1251/рваных строк в широких матрицах, отсутствующих таблиц и manifest.json."""
    # 1. Отсутствует директория или обязательная таблица Источники.csv
    missing_bundle = ingest_any_source(tmp_path / "nonexistent_city")
    assert missing_bundle.has_fatal_ingestion_error

    partial_dir = tmp_path / "incomplete_city"
    partial_dir.mkdir()
    (partial_dir / "Узел.csv").write_text("ID,Высота\nc1,10.0\n", encoding="utf-8")
    (partial_dir / "Труба.csv").write_text("ID,Начало,Конец,Диаметр,Длина\ne1,c1,c1,100,10\n", encoding="utf-8")
    partial_bundle = ingest_any_source(partial_dir)
    assert any(i.code == CheckCode.MISSING_FILE for i in partial_bundle.ingestion_issues)

    # 2. Широкая матрица с UTF-8 BOM, cp1251 и рваной строкой
    cdir = build_city_13_csv_folder(tmp_path / "хорезмская", broken_self_loop_topology=False)
    bom_wide = "\ufeffID,R0,R1,R2\nv1284,10.0,11.0,12.0\n".encode("utf-8")
    (cdir / "Поток Клапан.csv").write_bytes(bom_wide)

    cp1251_wide = "ID,R0,R1\np1263,0.0,0.0\np1264,5.0,6.0\n".encode("cp1251")
    (cdir / "Поток Насос.csv").write_bytes(cp1251_wide)

    ragged_wide = "ID,R0,R1,R2\ne702,1.0,2.0\n"
    (cdir / "Поток Труба.csv").write_text(ragged_wide, encoding="utf-8")

    # Битый manifest.json внутри папки города
    (cdir / "manifest.json").write_text("{not_valid_json", encoding="utf-8")

    b_edge = ingest_any_source(cdir)
    assert any(i.code == CheckCode.MANIFEST_INVALID for i in b_edge.ingestion_issues)
    assert b_edge.tables["wide/valve_flow.csv"].has_bom is True
    assert len(b_edge.tables["wide/pipe_flow.csv"].ragged_rows) == 1

