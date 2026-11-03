"""Подэтап 3.9 — Флаги качества, запись normalized/*.parquet и quality_report.json (§4, п. 3.9–3.10)."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from aquabit_ai.preprocess.log import PreprocessingLogger
from aquabit_ai.preprocess.s3_8_missing_values import inspect_column_masks


STAGE_NAME = "3.9_quality_flags"
DEFAULT_THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "config" / "quality_thresholds.yaml"


def load_quality_thresholds(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_THRESHOLDS_PATH
    return yaml.safe_load(target.read_text(encoding="utf-8"))


def _check_value_out_of_range(val: float, rule: dict[str, Any]) -> bool:
    check_v = abs(val) if rule.get("use_abs", False) else val
    if "min_inclusive" in rule and check_v < float(rule["min_inclusive"]):
        return True
    if "min_exclusive" in rule and check_v <= float(rule["min_exclusive"]):
        return True
    if "max_inclusive" in rule and check_v > float(rule["max_inclusive"]):
        return True
    if "max_exclusive" in rule and check_v >= float(rule["max_exclusive"]):
        return True
    return False


def _compute_robust_zscore_flags(
    values: list[float | None],
    is_null: list[bool],
    is_nan: list[bool],
    ref_median: float,
    ref_mad: float,
    threshold: float = 3.5,
) -> list[bool | None]:
    flags: list[bool | None] = []
    for i, val in enumerate(values):
        if is_null[i] or is_nan[i] or val is None:
            flags.append(None)
            continue
        if ref_mad == 0.0:
            flags.append(abs(val - ref_median) > 0.0)
        else:
            rz = abs(0.6745 * (val - ref_median) / ref_mad)
            flags.append(rz > threshold)
    return flags


def _estimate_median_and_mad(finite_vals: list[float]) -> tuple[float, float] | None:
    if len(finite_vals) < 5:
        return None
    med = statistics.median(finite_vals)
    abs_devs = [abs(x - med) for x in finite_vals]
    mad = statistics.median(abs_devs)
    return (med, mad)


def compute_quality_flags_and_report(
    tables: dict[str, pd.DataFrame],
    converted_fields: set[tuple[str, str]],
    table_gap_flags: dict[str, list[bool]],
    logger: PreprocessingLogger,
    *,
    thresholds_config: dict[str, Any] | None = None,
    historical_baseline: dict[tuple[str, str], dict[str, float]] | None = None,
) -> tuple[dict[str, pa.Table], dict[str, Any]]:
    """Рассчитывает флаги качества по всем таблицам и формирует структуру quality_report.json (§3.9, §3.10).

    historical_baseline: опциональный словарь {(file, field): {"median": ..., "mad": ...}}.
    Если исторических данных для поля нет, флаг is_outlier выставляется в None (null), как требует §3.9.
    """
    cfg = thresholds_config or load_quality_thresholds()
    rz_threshold = float(cfg.get("robust_zscore_threshold", 3.5))
    range_rules_all: dict[str, dict[str, Any]] = cfg.get("ranges", {})

    quality_tables: dict[str, pa.Table] = {}
    report: dict[str, Any] = {}
    warning_reasons: list[str] = []

    for rel_path, df in sorted(tables.items()):
        n_rows = len(df)
        file_ranges = range_rules_all.get(rel_path, {})
        gap_flags = table_gap_flags.get(rel_path, [False] * n_rows)

        q_arrays: dict[str, pa.Array] = {}
        if "id" in df.columns:
            q_arrays["id"] = df["id"].array._pa_array  # type: ignore[attr-defined]
        q_arrays["timestamp_gap"] = pa.array(gap_flags, type=pa.bool_())

        nulls_by_field: dict[str, int] = {}
        zeros_by_field: dict[str, int] = {}
        nans_by_field: dict[str, int] = {}
        out_of_range_counts: dict[str, int] = {}
        outlier_counts: dict[str, int] = {}
        file_converted_cols: list[str] = []

        for col in df.columns:
            null_m, zero_m, nan_m = inspect_column_masks(df[col])
            nulls_by_field[col] = sum(null_m)
            if sum(zero_m) > 0:
                zeros_by_field[col] = sum(zero_m)
            if sum(nan_m) > 0:
                nans_by_field[col] = sum(nan_m)

            pa_arr = df[col].array._pa_array  # type: ignore[attr-defined]
            if isinstance(pa_arr, pa.ChunkedArray):
                pa_arr = pa_arr.combine_chunks()

            is_conv = (rel_path, col) in converted_fields
            if is_conv:
                file_converted_cols.append(col)

            # Диапазоны и выбросы проверяются для числовых колонок
            if pa.types.is_floating(pa_arr.type) or pa.types.is_integer(pa_arr.type):
                raw_pylist = pa_arr.to_pylist()
                num_vals: list[float | None] = [
                    None if null_m[i] else float(raw_pylist[i]) for i in range(n_rows)
                ]

                # 1. is_out_of_range по паспортным пределам
                col_range_rule = file_ranges.get(col)
                oor_flags: list[bool] = []
                for i, val in enumerate(num_vals):
                    if val is None or nan_m[i] or col_range_rule is None:
                        oor_flags.append(False)
                    else:
                        oor_flags.append(_check_value_out_of_range(val, col_range_rule))
                n_oor = sum(oor_flags)
                if n_oor > 0:
                    out_of_range_counts[col] = n_oor
                    warning_reasons.append(f"{n_oor} out_of_range values in {rel_path}:{col}")

                # 2. is_outlier по robust z-score к историческим данным (если есть; иначе null — §3.9)
                hist_key = (rel_path, col)
                if historical_baseline and hist_key in historical_baseline:
                    ref_med = float(historical_baseline[hist_key]["median"])
                    ref_mad = float(historical_baseline[hist_key]["mad"])
                    outlier_flags = _compute_robust_zscore_flags(
                        num_vals, null_m, nan_m, ref_med, ref_mad, rz_threshold
                    )
                    n_out = sum(1 for fl in outlier_flags if fl is True)
                    outlier_counts[col] = n_out
                    if n_out > 0:
                        warning_reasons.append(
                            f"{n_out} historical outliers in {rel_path}:{col}"
                        )
                else:
                    outlier_flags = [None] * n_rows
                    # Для сводки quality_report.json оцениваем выборочные robust-выбросы при MAD > 0
                    finite = [
                        v
                        for i, v in enumerate(num_vals)
                        if v is not None and not nan_m[i] and not math.isnan(v)
                    ]
                    est = _estimate_median_and_mad(finite)
                    if est is not None and est[1] > 0.0:
                        dist_flags = _compute_robust_zscore_flags(
                            num_vals, null_m, nan_m, est[0], est[1], rz_threshold
                        )
                        n_dist = sum(1 for fl in dist_flags if fl is True)
                        if n_dist > 0:
                            outlier_counts[col] = n_dist
            else:
                oor_flags = [False] * n_rows
                outlier_flags = [None] * n_rows

            q_arrays[f"{col}__is_null"] = pa.array(null_m, type=pa.bool_())
            q_arrays[f"{col}__is_zero"] = pa.array(zero_m, type=pa.bool_())
            q_arrays[f"{col}__is_outlier"] = pa.array(outlier_flags, type=pa.bool_())
            q_arrays[f"{col}__is_out_of_range"] = pa.array(oor_flags, type=pa.bool_())
            q_arrays[f"{col}__unit_converted"] = pa.array([is_conv] * n_rows, type=pa.bool_())

        n_gaps = sum(gap_flags)
        if n_gaps > 0:
            warning_reasons.append(f"{n_gaps} timestamp gaps in {rel_path}")
        if file_converted_cols:
            warning_reasons.append(
                f"unit conversion in {rel_path}: {', '.join(file_converted_cols)}"
            )

        quality_tables[rel_path] = pa.table(q_arrays)
        report[rel_path] = {
            "rows": n_rows,
            "nulls_by_field": nulls_by_field,
            "zeros_by_field": zeros_by_field,
            "nans_by_field": nans_by_field,
            "out_of_range": out_of_range_counts,
            "outliers": outlier_counts,
            "unit_converted_fields": file_converted_cols,
            "timestamp_gaps": n_gaps,
        }

    # Также учитываем предупреждения из предыдущих подэтапов 3.1–3.7 (перекодировка, разделитель и т.д.)
    for warn_entry in logger.warnings():
        if warn_entry.stage in {"3.1_encoding_delimiter", "3.3_field_canonicalization", "3.7_cross_references"}:
            reason = f"{warn_entry.operation} in {warn_entry.file or 'bundle'}"
            if reason not in warning_reasons:
                warning_reasons.append(reason)

    report["overall"] = {
        "status": "warning" if warning_reasons else "ok",
        "reasons": warning_reasons,
    }

    logger.record(
        stage=STAGE_NAME,
        operation="compute_quality_flags_and_summary",
        affected_rows=sum(len(df) for df in tables.values()),
        severity="warning" if warning_reasons else "info",
        details={
            "overall_status": report["overall"]["status"],
            "warning_reasons_count": len(warning_reasons),
        },
    )

    return quality_tables, report


def write_normalized_parquet_and_reports(
    tables: dict[str, pd.DataFrame],
    quality_tables: dict[str, pa.Table],
    quality_report: dict[str, Any],
    entity_registry_dict: dict[str, dict[str, Any]],
    logger: PreprocessingLogger,
    output_dir: Path,
) -> dict[str, Path]:
    """Сохраняет normalized/*.parquet, normalized/_quality/*.parquet, preprocessing_log.jsonl и quality_report.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    norm_dir = output_dir / "normalized"
    qual_dir = norm_dir / "_quality"

    written_parquets: dict[str, Path] = {}
    for rel_path, df in sorted(tables.items()):
        parquet_rel = Path(rel_path).with_suffix(".parquet")
        target_pq = norm_dir / parquet_rel
        target_pq.parent.mkdir(parents=True, exist_ok=True)

        # Собираем pa.Table напрямую из ArrowExtensionArray колонок для 100% сохранения null vs NaN
        pa_cols: dict[str, pa.Array] = {}
        for col in df.columns:
            pa_arr = df[col].array._pa_array  # type: ignore[attr-defined]
            if isinstance(pa_arr, pa.ChunkedArray):
                pa_arr = pa_arr.combine_chunks()
            pa_cols[col] = pa_arr
        pq.write_table(pa.table(pa_cols), target_pq)
        written_parquets[rel_path] = target_pq

        q_tbl = quality_tables.get(rel_path)
        if q_tbl is not None:
            q_pq = qual_dir / parquet_rel
            q_pq.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(q_tbl, q_pq)

    q_report_path = output_dir / "quality_report.json"
    q_report_path.write_text(
        json.dumps(quality_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    reg_path = output_dir / "entity_registry.json"
    reg_path.write_text(
        json.dumps(entity_registry_dict, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log_path = logger.write_jsonl(output_dir / "preprocessing_log.jsonl")
    return {
        "normalized_dir": norm_dir,
        "quality_report": q_report_path,
        "entity_registry": reg_path,
        "preprocessing_log": log_path,
    }
