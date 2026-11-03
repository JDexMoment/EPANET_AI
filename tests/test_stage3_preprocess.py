"""Юнит-тесты всех 9 подэтапов Этапа 3 — Preprocessing (§4, п. 3.1–3.10)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from aquabit_ai.config import AliasRegistry
from aquabit_ai.ingest import ingest_zip_archive
from aquabit_ai.preprocess import (
    PreprocessingFatalError,
    PreprocessingLogger,
    apply_column_typing,
    audit_missing_values,
    build_entity_registry,
    canonicalize_field_names,
    canonicalize_timestamps,
    canonicalize_units,
    compute_quality_flags_and_report,
    decode_and_parse_raw_csv_bytes,
    inspect_column_masks,
    run_preprocessing,
    verify_and_normalize_cross_references,
)
from tests.conftest import build_valid_files_map, write_zip_from_map


def test_s3_1_encoding_cp1251_tab_and_corrupt_binary() -> None:
    logger = PreprocessingLogger()
    raw_cp1251_tsv = "id\tname\televation_m\n001\tУзел-Север\t12.5\n".encode("cp1251")
    df = decode_and_parse_raw_csv_bytes("nodes.csv", raw_cp1251_tsv, logger)
    assert list(df.columns) == ["id", "name", "elevation_m"]
    assert df["id"].tolist() == ["001"]
    assert df["name"].tolist() == ["Узел-Север"]
    assert logger.entries[0].severity == "warning"
    assert logger.entries[0].details["detected_encoding"] == "cp1251"
    assert logger.entries[0].details["detected_delimiter"] == "\t"
    assert logger.entries[0].details["transcoded_to_utf8"] is True

    # Нечитаемые байты, которые невалидны даже в cp1251 (байт 0x98 не определён в Windows-1251)
    bad_bytes = b"id,name\n001,\x98\xff\xfe\n"
    with pytest.raises(PreprocessingFatalError) as exc_info:
        decode_and_parse_raw_csv_bytes("broken.csv", bad_bytes, logger)
    assert exc_info.value.code == "ENCODING_ERROR"


def test_s3_2_and_s3_8_empty_is_null_zero_is_zero_nan_is_nan_and_leading_zeros(
    tmp_path: Path,
) -> None:
    """Обязательный тест §3.10: '' -> null, '0' -> 0.0, 'NaN' -> NaN, ведущие нули сохраняются."""
    files = build_valid_files_map(with_results=True)
    files["nodes.csv"] = (
        "id,name,elevation_m,required_pressure_m,calculated_head_m\n"
        "0001,Узел-1,10.0,,42.5\n"
        "0002,Узел-2,0,0,0.0\n"
        "N_003,Узел-3,15.0,20.0,31.0\n"
    ).encode("utf-8")
    files["pipes.csv"] = (
        "id,start_node_id,end_node_id,length_m,diameter_mm,velocity_m_s\n"
        "001100000415,SRC_01,0001,450.0,300,1.2\n"
        "P_02,0002,N_003,620.5,200,NaN\n"
    ).encode("utf-8")
    files["pumps.csv"] = b"id,start_node_id,end_node_id\nPUMP_36,0001,0002\n"
    files["demands.csv"] = b"node_id,base_demand_m3_h,curve_id\n0002,120.0,PAT_RESIDENTIAL\n"
    files["timeseries/node_pressure.csv"] = (
        "id,time_iso8601,head_m\n"
        "0001,2026-10-30T00:00:00+05:00,42.5\n"
        "0002,2026-10-30T00:00:00+05:00,0\n"
    ).encode("utf-8")

    z_path = write_zip_from_map(tmp_path / "null_zero_nan.zip", files)
    out_dir = tmp_path / "out_pq"
    outcome = run_preprocessing(ingest_zip_archive(z_path), output_dir=out_dir)

    # Проверяем после полного Parquet roundtrip!
    nodes_pq = pq.read_table(out_dir / "normalized" / "nodes.parquet")
    assert nodes_pq["id"].to_pylist() == ["0001", "0002", "N_003"]
    assert nodes_pq["required_pressure_m"].is_null().to_pylist() == [True, False, False]
    assert nodes_pq["required_pressure_m"].to_pylist() == [None, 0.0, 20.0]

    pipes_pq = pq.read_table(out_dir / "normalized" / "pipes.parquet")
    assert pipes_pq["id"].to_pylist() == ["001100000415", "P_02"]
    assert pipes_pq["velocity_m_s"].is_null().to_pylist() == [False, False]
    assert pc.is_nan(pipes_pq["velocity_m_s"]).to_pylist() == [False, True]

    # Маски Substage 3.8
    null_m, zero_m, nan_m = inspect_column_masks(outcome.tables["nodes.csv"]["required_pressure_m"])
    assert null_m == [True, False, False]
    assert zero_m == [False, True, False]
    assert nan_m == [False, False, False]


def test_s3_2_rejects_comma_decimal_missing_tz_bad_bool_and_bad_enum() -> None:
    registry = AliasRegistry.from_yaml()
    logger = PreprocessingLogger()

    # 1. Запятая в числе -> LOCALE_DECIMAL_MISMATCH
    df_comma = pd.DataFrame({"id": ["01"], "elevation_m": ["12,5"]})
    with pytest.raises(PreprocessingFatalError) as e1:
        apply_column_typing({"nodes.csv": df_comma}, registry, logger)
    assert e1.value.code == "LOCALE_DECIMAL_MISMATCH"

    # 2. Timestamp без таймзоны -> TIMESTAMP_WITHOUT_TZ
    df_tz = pd.DataFrame({"id": ["01"], "time_iso8601": ["2026-10-30T01:00:00"], "head_m": ["30.0"]})
    with pytest.raises(PreprocessingFatalError) as e2:
        apply_column_typing({"timeseries/node_pressure.csv": df_tz}, registry, logger)
    assert e2.value.code == "TIMESTAMP_WITHOUT_TZ"

    # 3. Некорректный bool -> INVALID_BOOL_VALUE
    df_bool = pd.DataFrame({"id": ["01"], "elevation_m": ["10.0"], "is_active": ["maybe"]})
    with pytest.raises(PreprocessingFatalError) as e3:
        apply_column_typing({"nodes.csv": df_bool}, registry, logger)
    assert e3.value.code == "INVALID_BOOL_VALUE"

    # 4. Некорректный enum state -> INVALID_ENUM_VALUE
    df_enum = pd.DataFrame(
        {
            "id": ["PUMP_1"],
            "time_iso8601": ["2026-10-30T00:00:00+05:00"],
            "flow_m3_h": ["100.0"],
            "head_m": ["30.0"],
            "state": ["BROKEN_UNKNOWN_STATE"],
        }
    )
    with pytest.raises(PreprocessingFatalError) as e4:
        apply_column_typing({"timeseries/pump_state.csv": df_enum}, registry, logger)
    assert e4.value.code == "INVALID_ENUM_VALUE"


def test_s3_3_and_s3_4_unit_conversion_l_s_to_m3_h_and_km_to_m() -> None:
    registry = AliasRegistry.from_yaml()
    logger = PreprocessingLogger()

    raw_pipes = pd.DataFrame(
        {
            "id": ["P_01", "P_02"],
            "start_node_id": ["N1", "N2"],
            "end_node_id": ["N2", "N3"],
            "length_km": ["1.5", "0"],
            "diameter_mm": ["300", "200"],
            "flow_l_s": ["10.0", ""],
        }
    )
    typed = apply_column_typing({"pipes.csv": raw_pipes}, registry, logger)
    s3_tables, pending = canonicalize_field_names(typed, registry, logger)
    assert "flow_l_s" in s3_tables["pipes.csv"].columns
    assert "length_km" in s3_tables["pipes.csv"].columns

    s4_tables, converted = canonicalize_units(s3_tables, pending, None, logger)
    pipes_df = s4_tables["pipes.csv"]
    assert ("pipes.csv", "flow_m3_h") in converted
    assert ("pipes.csv", "length_m") in converted
    assert pipes_df["length_m"].array._pa_array.to_pylist() == [1500.0, 0.0]
    assert pipes_df["flow_m3_h"].array._pa_array.to_pylist() == [36.0, None]
    # Для гидравлической величины flow_l_s лог содержит warning (§3.4)
    assert any(
        e.stage == "3.4_unit_canonicalization"
        and e.field == "flow_m3_h"
        and e.severity == "warning"
        for e in logger.entries
    )


def test_s3_5_timeseries_gap_inserts_null_without_interpolation(tmp_path: Path) -> None:
    """Обязательный тест §3.10: временной ряд с дырой -> null на месте дыры (без интерполяции)."""
    files = build_valid_files_map(with_results=True)
    # Пропущен шаг 01:00 между 00:00 и 02:00 (при step_seconds=3600) + вход в UTC 'Z'
    files["timeseries/node_pressure.csv"] = (
        "id,time_iso8601,head_m\n"
        "001,2026-10-29T19:00:00Z,40.0\n"
        "001,2026-10-29T21:00:00Z,50.0\n"
    ).encode("utf-8")

    z_path = write_zip_from_map(tmp_path / "gap_ts.zip", files)
    outcome = run_preprocessing(ingest_zip_archive(z_path))

    ts_df = outcome.tables["timeseries/node_pressure.csv"]
    assert len(ts_df) == 3
    times = ts_df["time_iso8601"].array._pa_array.to_pylist()
    heads = ts_df["head_m"].array._pa_array.to_pylist()
    assert times == [
        "2026-10-30T00:00:00+05:00",
        "2026-10-30T01:00:00+05:00",
        "2026-10-30T02:00:00+05:00",
    ]
    # Строго None (null) на месте дыры 01:00, а НЕ среднее 45.0!
    assert heads == [40.0, None, 50.0]
    assert outcome.table_gap_flags["timeseries/node_pressure.csv"] == [False, True, False]


def test_s3_6_s3_7_s3_8_fatal_on_duplicate_id_orphan_and_null_mandatory() -> None:
    registry = AliasRegistry.from_yaml()
    logger = PreprocessingLogger()

    # 1. Дублирующиеся ID -> DUPLICATE_ID (fatal)
    dup_nodes = apply_column_typing(
        {"nodes.csv": pd.DataFrame({"id": ["001", "001"], "elevation_m": ["10.0", "12.0"]})},
        registry,
        logger,
    )
    with pytest.raises(PreprocessingFatalError) as e_dup:
        build_entity_registry(dup_nodes, logger)
    assert e_dup.value.code == "DUPLICATE_ID"

    # 2. Осиротевшие ссылки -> ORPHAN_REFERENCE (fatal)
    clean_tables = apply_column_typing(
        {
            "nodes.csv": pd.DataFrame({"id": ["001"], "elevation_m": ["10.0"]}),
            "pipes.csv": pd.DataFrame(
                {
                    "id": ["P1"],
                    "start_node_id": ["001"],
                    "end_node_id": ["GHOST_99"],
                    "length_m": ["100.0"],
                    "diameter_mm": ["200"],
                }
            ),
        },
        registry,
        logger,
    )
    ent_reg = build_entity_registry(clean_tables, logger)
    with pytest.raises(PreprocessingFatalError) as e_orph:
        verify_and_normalize_cross_references(clean_tables, ent_reg, logger)
    assert e_orph.value.code == "ORPHAN_REFERENCE"

    # 3. Null в обязательном поле elevation_m -> MANDATORY_FIELD_NULL (fatal)
    null_elev = apply_column_typing(
        {"nodes.csv": pd.DataFrame({"id": ["001"], "elevation_m": [""]})},
        registry,
        logger,
    )
    with pytest.raises(PreprocessingFatalError) as e_null:
        audit_missing_values(null_elev, logger)
    assert e_null.value.code == "MANDATORY_FIELD_NULL"


def test_s3_9_out_of_range_velocity_and_historical_outliers(tmp_path: Path) -> None:
    """Обязательный тест §3.10: скорость > 5 м/с -> is_out_of_range=True; выбросы по истории."""
    files = build_valid_files_map(with_results=True)
    files["timeseries/pipe_velocity.csv"] = (
        "id,time_iso8601,velocity_m_s\n"
        "P_01,2026-10-30T00:00:00+05:00,1.4\n"
        "P_02,2026-10-30T00:00:00+05:00,6.8\n"
    ).encode("utf-8")
    z_path = write_zip_from_map(tmp_path / "oor.zip", files)

    # 1. Без исторической базы is_outlier == None (null) по §3.9
    out_no_hist = run_preprocessing(ingest_zip_archive(z_path))
    vel_q = out_no_hist.quality_tables["timeseries/pipe_velocity.csv"]
    assert vel_q["velocity_m_s__is_out_of_range"].to_pylist() == [False, True]
    assert vel_q["velocity_m_s__is_outlier"].to_pylist() == [None, None]
    assert out_no_hist.quality_report["timeseries/pipe_velocity.csv"]["out_of_range"] == {
        "velocity_m_s": 1
    }

    # 2. С исторической базой robust z-score выставляет булев флаг is_outlier
    out_with_hist = run_preprocessing(
        ingest_zip_archive(z_path),
        historical_baseline={
            ("nodes.csv", "calculated_head_m"): {"median": 31.5, "mad": 1.0},
        },
    )
    nodes_q = out_with_hist.quality_tables["nodes.csv"]
    # Для [42.5, 36.2, 31.0] относительно median=31.5, mad=1.0: 42.5 даёт rz = 0.6745*11 = 7.42 > 3.5 -> True
    assert nodes_q["calculated_head_m__is_outlier"].to_pylist() == [True, False, False]
