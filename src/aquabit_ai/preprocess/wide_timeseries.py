"""Векторизованная нормализация широких временны́х матриц R0..R{T-1} (ADR-0007).

Строго соблюдает Принципы 1, 2, 6, 7 и 8:
- никаких гидравлических формул в Python;
- только тривиальные описательные агрегаты (min, max, mean, count, zero_steps, negative_steps, sign_changes)
  и точные часовые срезы (R0, R60, ..., R1380 при n_steps=1440) без интерполяции;
- строгое разделение null (отсутствие данных), 0.0 (нулевое значение) и IEEE NaN (не применимо) в PyArrow;
- запись сжатых Zstd Parquet-файлов напрямую из C++-буферов PyArrow без разворачивания десятков
  миллионов строк в Python-циклы.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from aquabit_ai.ingest.archive import IngestionBundle
from aquabit_ai.ingest.city_folder import WideTimeseriesMatrix
from aquabit_ai.preprocess.log import PreprocessingLogger


STAGE_NAME = "3.10_wide_timeseries_vectorized"


@dataclass
class WidePreprocessArtifact:
    """Результат векторизованной обработки одной широкой матрицы ID,R0..R{T-1}."""

    canonical_path: str
    source_filename: str
    canonical_metric: str
    n_rows: int
    n_steps: int
    step_seconds: int
    null_cells: int
    zero_cells: int
    nan_cells: int
    wide_table: pa.Table
    summary_table: pa.Table


def build_wide_matrix_artifacts(
    bundle: IngestionBundle,
    logger: PreprocessingLogger,
) -> dict[str, WidePreprocessArtifact]:
    """Вычисляет канонические PyArrow-таблицы и векторизованные сводки по всем wide/* матрицам."""
    artifacts: dict[str, WidePreprocessArtifact] = {}

    for rel_path, ingested in sorted(bundle.tables.items()):
        if ingested.wide_matrix is None:
            continue

        w: WideTimeseriesMatrix = ingested.wide_matrix
        n_rows = w.num_rows
        n_steps = w.n_steps
        metric = w.canonical_metric

        # Переименовываем первую колонку в каноническое 'id' без копирования буферов
        new_names = ["id", *w.step_columns]
        meta_bytes = {
            b"canonical_metric": metric.encode("utf-8"),
            b"target_entity_type": w.target_entity_type.encode("utf-8"),
            b"step_seconds": str(w.step_seconds).encode("utf-8"),
            b"n_steps": str(n_steps).encode("utf-8"),
            b"source_file": w.source_filename.encode("utf-8"),
        }
        wide_pa = w.arrow_table.rename_columns(new_names).replace_schema_metadata(meta_bytes)

        # Векторизованный расчёт статистик по матрице [N, T] с точным учётом null vs NaN
        mat, null_mask = w.to_numpy_with_null_mask()
        # Ячейки, которые в исходном Arrow НЕ были null, но имеют np.isnan -> настоящие IEEE NaN!
        ieee_nan_mask = (~null_mask) & np.isnan(mat)
        valid_mask = (~null_mask) & (~ieee_nan_mask)

        total_nulls = int(np.count_nonzero(null_mask))
        total_nans = int(np.count_nonzero(ieee_nan_mask))
        zero_mask = valid_mask & (mat == 0.0)
        total_zeros = int(np.count_nonzero(zero_mask))
        neg_mask = valid_mask & (mat < 0.0)

        non_null_steps = np.sum(~null_mask, axis=1).astype(np.int64)
        null_steps = np.sum(null_mask, axis=1).astype(np.int64)
        nan_steps = np.sum(ieee_nan_mask, axis=1).astype(np.int64)
        valid_steps = np.sum(valid_mask, axis=1).astype(np.int64)
        zero_steps = np.sum(zero_mask, axis=1).astype(np.int64)
        neg_steps = np.sum(neg_mask, axis=1).astype(np.int64)

        # Число смен знака потока (> +1e-9 <-> < -1e-9) по строке без учёта нулей
        if n_rows > 0 and n_steps > 1:
            signs = np.where(valid_mask, np.where(mat > 1e-9, 1, np.where(mat < -1e-9, -1, 0)), 0)
            # Считаем смену знака между соседними ненулевыми отсчётами векторно/компактно
            sign_changes = np.zeros(n_rows, dtype=np.int64)
            has_both = (np.any(signs > 0, axis=1)) & (np.any(signs < 0, axis=1))
            for i in np.flatnonzero(has_both):
                nz = signs[i][signs[i] != 0]
                if nz.size > 1:
                    sign_changes[i] = int(np.count_nonzero(nz[1:] != nz[:-1]))
        else:
            sign_changes = np.zeros(n_rows, dtype=np.int64)

        # Векторизованные min, max, mean (строго null там, где valid_steps == 0)
        if n_rows > 0 and n_steps > 0:
            mat_for_min = np.where(valid_mask, mat, np.inf)
            mat_for_max = np.where(valid_mask, mat, -np.inf)
            mat_for_sum = np.where(valid_mask, mat, 0.0)

            raw_min = np.min(mat_for_min, axis=1)
            raw_max = np.max(mat_for_max, axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                raw_mean = np.where(valid_steps > 0, np.sum(mat_for_sum, axis=1) / valid_steps, 0.0)

            min_list = [None if valid_steps[i] == 0 else float(raw_min[i]) for i in range(n_rows)]
            max_list = [None if valid_steps[i] == 0 else float(raw_max[i]) for i in range(n_rows)]
            mean_list = [None if valid_steps[i] == 0 else float(raw_mean[i]) for i in range(n_rows)]
        else:
            min_list = []
            max_list = []
            mean_list = []

        summary_cols: dict[str, pa.Array] = {
            "id": wide_pa.column("id").combine_chunks(),
            f"min_{metric}": pa.array(min_list, type=pa.float64(), from_pandas=False),
            f"max_{metric}": pa.array(max_list, type=pa.float64(), from_pandas=False),
            f"mean_{metric}": pa.array(mean_list, type=pa.float64(), from_pandas=False),
            "n_steps_total": pa.array(np.full(n_rows, n_steps, dtype=np.int64), type=pa.int64()),
            "non_null_steps": pa.array(non_null_steps, type=pa.int64()),
            "null_steps": pa.array(null_steps, type=pa.int64()),
            "nan_steps": pa.array(nan_steps, type=pa.int64()),
            "zero_steps": pa.array(zero_steps, type=pa.int64()),
            "negative_steps": pa.array(neg_steps, type=pa.int64()),
            "sign_changes_count": pa.array(sign_changes, type=pa.int64()),
        }

        # Точные часовые срезы AquaBit (R0, R60, ..., R1380) при минутном шаге без какой-либо интерполяции
        if n_steps == 1440:
            for hour in range(24):
                col_rk = f"R{hour * 60}"
                summary_cols[f"h{hour:02d}_{metric}"] = wide_pa.column(col_rk).combine_chunks()

        summary_pa = pa.table(summary_cols).replace_schema_metadata(meta_bytes)

        logger.record(
            stage=STAGE_NAME,
            operation="vectorized_wide_matrix_normalization",
            file=rel_path,
            field=metric,
            affected_rows=n_rows,
            severity="info",
            details={
                "source_file": w.source_filename,
                "n_rows": n_rows,
                "n_steps": n_steps,
                "step_seconds": w.step_seconds,
                "null_cells": total_nulls,
                "zero_cells": total_zeros,
                "nan_cells": total_nans,
            },
        )

        artifacts[rel_path] = WidePreprocessArtifact(
            canonical_path=rel_path,
            source_filename=w.source_filename,
            canonical_metric=metric,
            n_rows=n_rows,
            n_steps=n_steps,
            step_seconds=w.step_seconds,
            null_cells=total_nulls,
            zero_cells=total_zeros,
            nan_cells=total_nans,
            wide_table=wide_pa,
            summary_table=summary_pa,
        )

    return artifacts


def write_wide_parquet_artifacts(
    wide_artifacts: dict[str, WidePreprocessArtifact],
    output_dir: Path,
) -> dict[str, Path]:
    """Записывает сжатые Zstd Parquet-таблицы wide/* и wide_summary/*."""
    written: dict[str, Path] = {}
    if not wide_artifacts:
        return written

    norm_dir = output_dir / "normalized"
    summary_dir = norm_dir / "wide_summary"

    for rel_path, art in sorted(wide_artifacts.items()):
        pq_rel = Path(rel_path).with_suffix(".parquet")
        wide_pq = norm_dir / pq_rel
        wide_pq.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(art.wide_table, wide_pq, compression="zstd")
        written[f"parquet:{rel_path}"] = wide_pq

        sum_pq = summary_dir / pq_rel.name
        sum_pq.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(art.summary_table, sum_pq, compression="zstd")
        written[f"summary:{rel_path}"] = sum_pq

    return written
