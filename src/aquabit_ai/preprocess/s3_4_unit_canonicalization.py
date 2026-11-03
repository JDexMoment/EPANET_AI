"""Подэтап 3.4 — Канонизация единиц измерения к manifest.units с пометкой unit_converted (§4, п. 3.4)."""

from __future__ import annotations

import math

import pandas as pd
import pyarrow as pa

from aquabit_ai.config.csv_contracts import NonCanonicalColumnRule
from aquabit_ai.config.manifest import UnitsMetadata
from aquabit_ai.preprocess.log import PreprocessingLogger


STAGE_NAME = "3.4_unit_canonicalization"


def _extract_arrow_float_list(series: pd.Series) -> tuple[list[float | None], list[bool]]:
    """Извлекает список (float | None) и маску is_null без смешения None и IEEE NaN."""
    pa_arr = series.array._pa_array  # type: ignore[attr-defined]
    if isinstance(pa_arr, pa.ChunkedArray):
        pa_arr = pa_arr.combine_chunks()
    null_mask = pa_arr.is_null().to_pylist()
    raw_pylist = pa_arr.to_pylist()
    values: list[float | None] = []
    for is_null, val in zip(null_mask, raw_pylist):
        if is_null:
            values.append(None)
        else:
            values.append(float(val))
    return values, null_mask


def canonicalize_units(
    tables: dict[str, pd.DataFrame],
    pending_unit_rules: dict[tuple[str, str], NonCanonicalColumnRule],
    manifest_units: UnitsMetadata | None,
    logger: PreprocessingLogger,
) -> tuple[dict[str, pd.DataFrame], set[tuple[str, str]]]:
    """Приводит колонки с неканоническими единицами к каноническим из manifest.units (§4, п. 3.4).

    Никаких физических пересчётов гидравлики (например, давление <-> напор через плотность) —
    только строгие линейные множители размерности (л/с -> м3/ч, км -> м, кПа -> бар).
    Возвращает (обновлённые таблицы, множество сконвертированных полей {(file, col)}).
    """
    out_tables: dict[str, pd.DataFrame] = {}
    converted_fields: set[tuple[str, str]] = set()

    for rel_path, df in sorted(tables.items()):
        matching_cols = [
            (col_name, rule)
            for (f_path, col_name), rule in pending_unit_rules.items()
            if f_path == rel_path and col_name in df.columns
        ]
        if not matching_cols:
            out_tables[rel_path] = df
            continue

        new_df = df.copy()
        for src_col, rule in matching_cols:
            values, _ = _extract_arrow_float_list(new_df[src_col])
            mult = rule.conversion.multiplier
            scaled: list[float | None] = []
            affected = 0

            for v in values:
                if v is None:
                    scaled.append(None)
                elif math.isnan(v):
                    scaled.append(float("nan"))
                else:
                    affected += 1
                    res = v * mult
                    scaled.append(0.0 if res == 0.0 else res)

            arr = pa.array(scaled, type=pa.float64(), from_pandas=False)
            target_col = rule.target_canonical
            col_idx = list(new_df.columns).index(src_col)
            new_df = new_df.drop(columns=[src_col])
            new_df.insert(
                col_idx,
                target_col,
                pd.Series(pd.arrays.ArrowExtensionArray(arr), name=target_col, index=new_df.index),
            )

            converted_fields.add((rel_path, target_col))
            severity = "warning" if rule.is_hydraulic_quantity else "info"
            logger.record(
                stage=STAGE_NAME,
                operation="convert_unit_linear",
                file=rel_path,
                field=target_col,
                before={"column": src_col, "unit": rule.conversion.from_unit},
                after={"column": target_col, "unit": rule.conversion.to_unit},
                affected_rows=affected,
                severity=severity,
                details={
                    "multiplier": mult,
                    "is_hydraulic_quantity": rule.is_hydraulic_quantity,
                    "unit_converted": True,
                    "manifest_target_units": (
                        manifest_units.model_dump(mode="json") if manifest_units else None
                    ),
                },
            )

        out_tables[rel_path] = new_df

    return out_tables, converted_fields
