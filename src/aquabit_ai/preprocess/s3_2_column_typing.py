"""Подэтап 3.2 — Строгая типизация колонок через PyArrow/pandas без неявных приведений (§4, п. 3.2)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd
import pyarrow as pa

from aquabit_ai.config.csv_contracts import AliasRegistry, get_contract_for_path
from aquabit_ai.preprocess.errors import PreprocessingFatalError
from aquabit_ai.preprocess.log import PreprocessingLogger


STAGE_NAME = "3.2_column_typing"
NULL_STRINGS = {"", "null", "NULL", "None"}
NAN_STRINGS = {"NaN", "nan", "NAN"}
BOOL_MAP = {
    "true": True,
    "1": True,
    "yes": True,
    "false": False,
    "0": False,
    "no": False,
}


def _arrow_series(pa_arr: pa.Array, name: str, index: pd.Index) -> pd.Series:
    return pd.Series(pd.arrays.ArrowExtensionArray(pa_arr), name=name, index=index)


def _type_string_column(raw_values: list[str], col_name: str, index: pd.Index) -> tuple[pd.Series, int]:
    typed: list[str | None] = []
    nulls = 0
    for val in raw_values:
        # Для строковых ID и имён не применяем числовой парсинг; пустая строка -> null
        if val == "" or val.strip() in {"null", "NULL", "None"}:
            typed.append(None)
            nulls += 1
        else:
            typed.append(val)
    arr = pa.array(typed, type=pa.string())
    return _arrow_series(arr, col_name, index), nulls


def _type_float_column(
    raw_values: list[str],
    file_name: str,
    col_name: str,
    index: pd.Index,
) -> tuple[pd.Series, int, int, int]:
    typed: list[float | None] = []
    nulls = 0
    zeros = 0
    nans = 0

    for row_idx, raw in enumerate(raw_values, start=2):
        s = raw.strip()
        if s in NULL_STRINGS:
            typed.append(None)
            nulls += 1
            continue
        if s in NAN_STRINGS:
            typed.append(float("nan"))
            nans += 1
            continue
        if "," in s:
            raise PreprocessingFatalError(
                "LOCALE_DECIMAL_MISMATCH",
                f"Обнаружена запятая в числовом значении '{raw}' ({file_name}, колонка '{col_name}', строка {row_idx})",
                file=file_name,
                field=col_name,
                examples=[{"row_number": row_idx, "raw_value": raw}],
            )
        try:
            num = float(s)
        except ValueError as exc:
            raise PreprocessingFatalError(
                "INVALID_NUMERIC_VALUE",
                f"Некорректное число '{raw}' ({file_name}, колонка '{col_name}', строка {row_idx})",
                file=file_name,
                field=col_name,
                examples=[{"row_number": row_idx, "raw_value": raw}],
            ) from exc

        if math.isinf(num):
            raise PreprocessingFatalError(
                "INVALID_NUMERIC_VALUE",
                f"Бесконечное значение '{raw}' недопустимо ({file_name}, колонка '{col_name}', строка {row_idx})",
                file=file_name,
                field=col_name,
                examples=[{"row_number": row_idx, "raw_value": raw}],
            )
        if num == 0.0:
            num = 0.0  # нормализуем -0.0 -> 0.0
            zeros += 1
        typed.append(num)

    # from_pandas=False критично: None -> Arrow null, float('nan') -> IEEE NaN (различаются битмапом!)
    arr = pa.array(typed, type=pa.float64(), from_pandas=False)
    return _arrow_series(arr, col_name, index), nulls, zeros, nans


def _type_int_column(
    raw_values: list[str],
    file_name: str,
    col_name: str,
    index: pd.Index,
) -> tuple[pd.Series, int]:
    typed: list[int | None] = []
    nulls = 0
    for row_idx, raw in enumerate(raw_values, start=2):
        s = raw.strip()
        if s in NULL_STRINGS:
            typed.append(None)
            nulls += 1
            continue
        if "," in s:
            raise PreprocessingFatalError(
                "LOCALE_DECIMAL_MISMATCH",
                f"Обнаружена запятая в целочисленном поле '{raw}' ({file_name}, '{col_name}', строка {row_idx})",
                file=file_name,
                field=col_name,
                examples=[{"row_number": row_idx, "raw_value": raw}],
            )
        try:
            val = int(s)
        except ValueError as exc:
            raise PreprocessingFatalError(
                "INVALID_NUMERIC_VALUE",
                f"Ожидалось целое число, получено '{raw}' ({file_name}, '{col_name}', строка {row_idx})",
                file=file_name,
                field=col_name,
                examples=[{"row_number": row_idx, "raw_value": raw}],
            ) from exc
        typed.append(val)

    arr = pa.array(typed, type=pa.int64())
    return _arrow_series(arr, col_name, index), nulls


def _type_datetime_iso_column(
    raw_values: list[str],
    file_name: str,
    col_name: str,
    index: pd.Index,
) -> tuple[pd.Series, int]:
    typed: list[str | None] = []
    nulls = 0
    for row_idx, raw in enumerate(raw_values, start=2):
        s = raw.strip()
        if s in NULL_STRINGS:
            typed.append(None)
            nulls += 1
            continue
        iso_candidate = s[:-1] + "+00:00" if s.endswith("Z") else s
        try:
            dt = datetime.fromisoformat(iso_candidate)
        except ValueError as exc:
            raise PreprocessingFatalError(
                "INVALID_TIMESTAMP",
                f"Некорректная метка времени ISO 8601 '{raw}' ({file_name}, '{col_name}', строка {row_idx})",
                file=file_name,
                field=col_name,
                examples=[{"row_number": row_idx, "raw_value": raw}],
            ) from exc
        if dt.tzinfo is None:
            raise PreprocessingFatalError(
                "TIMESTAMP_WITHOUT_TZ",
                f"Метка времени без таймзоны '{raw}' ({file_name}, '{col_name}', строка {row_idx})",
                file=file_name,
                field=col_name,
                examples=[{"row_number": row_idx, "raw_value": raw}],
            )
        typed.append(s)

    arr = pa.array(typed, type=pa.string())
    return _arrow_series(arr, col_name, index), nulls


def _type_bool_column(
    raw_values: list[str],
    file_name: str,
    col_name: str,
    index: pd.Index,
) -> tuple[pd.Series, int]:
    typed: list[bool | None] = []
    nulls = 0
    for row_idx, raw in enumerate(raw_values, start=2):
        s = raw.strip()
        if s in NULL_STRINGS:
            typed.append(None)
            nulls += 1
            continue
        key = s.lower()
        if key not in BOOL_MAP:
            raise PreprocessingFatalError(
                "INVALID_BOOL_VALUE",
                f"Недопустимое булево значение '{raw}' ({file_name}, '{col_name}', строка {row_idx}). "
                "Допустимы только true/false/1/0/yes/no.",
                file=file_name,
                field=col_name,
                examples=[{"row_number": row_idx, "raw_value": raw}],
            )
        typed.append(BOOL_MAP[key])

    arr = pa.array(typed, type=pa.bool_())
    return _arrow_series(arr, col_name, index), nulls


def _type_enum_column(
    raw_values: list[str],
    allowed_values: tuple[str, ...],
    file_name: str,
    col_name: str,
    index: pd.Index,
) -> tuple[pd.Series, int]:
    allowed_set = set(allowed_values)
    typed: list[str | None] = []
    nulls = 0
    for row_idx, raw in enumerate(raw_values, start=2):
        s = raw.strip()
        if s in NULL_STRINGS:
            typed.append(None)
            nulls += 1
            continue
        if allowed_set and s not in allowed_set:
            raise PreprocessingFatalError(
                "INVALID_ENUM_VALUE",
                f"Недопустимое enum-значение '{raw}' ({file_name}, '{col_name}', строка {row_idx}). "
                f"Допустимые: {sorted(allowed_set)}",
                file=file_name,
                field=col_name,
                examples=[
                    {
                        "row_number": row_idx,
                        "raw_value": raw,
                        "allowed_values": sorted(allowed_set),
                    }
                ],
            )
        typed.append(s)

    arr = pa.array(typed, type=pa.string())
    return _arrow_series(arr, col_name, index), nulls


def apply_column_typing(
    tables: dict[str, pd.DataFrame],
    registry: AliasRegistry,
    logger: PreprocessingLogger,
) -> dict[str, pd.DataFrame]:
    """Подэтап 3.2: явное приведение типов колонок по схеме без потери различия null / 0.0 / NaN."""
    typed_tables: dict[str, pd.DataFrame] = {}

    for rel_path, df in sorted(tables.items()):
        contract = get_contract_for_path(rel_path)
        resolved = registry.resolve_table_headers(list(df.columns), contract)
        new_cols: dict[str, pd.Series] = {}

        for raw_col in df.columns:
            can_col = resolved.get(raw_col)
            fdef = registry.fields.get(can_col) if can_col is not None else None
            kind = fdef.kind if fdef is not None else "str_text"
            raw_vals = [str(v) for v in df[raw_col].tolist()]

            extra_details: dict[str, Any] = {"target_kind": kind}
            if kind in {"str_id", "str_text"}:
                series, nulls = _type_string_column(raw_vals, raw_col, df.index)
                target_dtype = "arrow_string"
            elif kind == "float_qty":
                series, nulls, zeros, nans = _type_float_column(
                    raw_vals, rel_path, raw_col, df.index
                )
                target_dtype = "arrow_float64"
                extra_details["zeros"] = zeros
                extra_details["nans"] = nans
            elif kind == "int_qty":
                series, nulls = _type_int_column(raw_vals, rel_path, raw_col, df.index)
                target_dtype = "arrow_int64"
            elif kind == "datetime_iso":
                series, nulls = _type_datetime_iso_column(raw_vals, rel_path, raw_col, df.index)
                target_dtype = "arrow_iso8601_string"
            elif kind == "bool_flag":
                series, nulls = _type_bool_column(raw_vals, rel_path, raw_col, df.index)
                target_dtype = "arrow_bool"
            elif kind == "enum_val":
                allowed = fdef.allowed_values if fdef is not None else ()
                series, nulls = _type_enum_column(raw_vals, allowed, rel_path, raw_col, df.index)
                target_dtype = "arrow_enum_string"
            else:
                series, nulls = _type_string_column(raw_vals, raw_col, df.index)
                target_dtype = "arrow_string"

            new_cols[raw_col] = series
            extra_details["nulls"] = nulls
            logger.record(
                stage=STAGE_NAME,
                operation="cast_column_type",
                file=rel_path,
                field=raw_col,
                before="raw_str",
                after=target_dtype,
                affected_rows=len(df),
                severity="info",
                details=extra_details,
            )

        typed_tables[rel_path] = pd.DataFrame(new_cols, index=df.index)

    return typed_tables
