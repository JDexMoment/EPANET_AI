"""Подэтап 3.8 — Строгий аудит пропусков (null vs 0.0 vs NaN) без импутации (§4, п. 3.8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

from aquabit_ai.config.csv_contracts import get_contract_for_path
from aquabit_ai.preprocess.errors import PreprocessingFatalError
from aquabit_ai.preprocess.log import PreprocessingLogger


STAGE_NAME = "3.8_missing_values"


@dataclass(frozen=True)
class ColumnMissingStats:
    """Точная статистика null / 0.0 / NaN по одной колонке."""

    null_count: int
    zero_count: int
    nan_count: int


def inspect_column_masks(series: pd.Series) -> tuple[list[bool], list[bool], list[bool]]:
    """Возвращает покомпонентные маски (is_null, is_zero, is_nan) с сохранением различия Arrow null и IEEE NaN."""
    pa_arr = series.array._pa_array  # type: ignore[attr-defined]
    if isinstance(pa_arr, pa.ChunkedArray):
        pa_arr = pa_arr.combine_chunks()

    is_null_list: list[bool] = pa_arr.is_null().to_pylist()
    n = len(is_null_list)

    if pa.types.is_floating(pa_arr.type):
        nan_raw = pc.is_nan(pa_arr).to_pylist()
        raw_vals = pa_arr.to_pylist()
        is_nan_list = [bool(nan_raw[i]) if not is_null_list[i] else False for i in range(n)]
        is_zero_list = [
            (not is_null_list[i] and not is_nan_list[i] and float(raw_vals[i]) == 0.0)
            for i in range(n)
        ]
        return is_null_list, is_zero_list, is_nan_list

    if pa.types.is_integer(pa_arr.type):
        raw_vals = pa_arr.to_pylist()
        is_nan_list = [False] * n
        is_zero_list = [(not is_null_list[i] and int(raw_vals[i]) == 0) for i in range(n)]
        return is_null_list, is_zero_list, is_nan_list

    return is_null_list, [False] * n, [False] * n


def audit_missing_values(
    tables: dict[str, pd.DataFrame],
    logger: PreprocessingLogger,
) -> dict[str, dict[str, ColumnMissingStats]]:
    """Проверяет отсутствие null в обязательных полях и фиксирует статистику null / 0.0 / NaN (§3.8).

    Заполнение пропусков средним/медианой/интерполяцией категорически запрещено.
    """
    stats_by_table: dict[str, dict[str, ColumnMissingStats]] = {}

    for rel_path, df in sorted(tables.items()):
        contract = get_contract_for_path(rel_path)
        is_timeseries = rel_path.startswith("timeseries/")

        # Во временных рядах обязательны только ключ объекта 'id' и 'time_iso8601';
        # метрики могут быть null (в том числе на месте дыр временного ряда — §3.5)
        if is_timeseries:
            mandatory_non_null = {"id", "time_iso8601"}
        elif contract is not None:
            mandatory_non_null = set(contract.required_columns)
        else:
            mandatory_non_null = set()

        col_stats: dict[str, ColumnMissingStats] = {}
        violation_examples: list[dict[str, Any]] = []

        for col in df.columns:
            null_m, zero_m, nan_m = inspect_column_masks(df[col])
            n_null = sum(null_m)
            n_zero = sum(zero_m)
            n_nan = sum(nan_m)
            col_stats[col] = ColumnMissingStats(
                null_count=n_null,
                zero_count=n_zero,
                nan_count=n_nan,
            )

            if col in mandatory_non_null and n_null > 0:
                null_rows = [i for i, flag in enumerate(null_m) if flag][:10]
                violation_examples.append(
                    {
                        "file": rel_path,
                        "field": col,
                        "null_count": n_null,
                        "sample_row_indices": null_rows,
                    }
                )

        if violation_examples:
            raise PreprocessingFatalError(
                "MANDATORY_FIELD_NULL",
                f"В обязательных полях таблицы '{rel_path}' обнаружены значения null",
                file=rel_path,
                examples=violation_examples,
            )

        stats_by_table[rel_path] = col_stats
        logger.record(
            stage=STAGE_NAME,
            operation="audit_missing_zero_nan",
            file=rel_path,
            affected_rows=len(df),
            severity="info",
            details={
                "nulls_by_field": {c: st.null_count for c, st in col_stats.items()},
                "zeros_by_field": {c: st.zero_count for c, st in col_stats.items()},
                "nans_by_field": {c: st.nan_count for c, st in col_stats.items()},
            },
        )

    return stats_by_table
