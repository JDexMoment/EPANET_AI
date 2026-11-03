"""Подэтап 3.5 — Канонизация времени, проверка шага и явная фиксация дыр как null без интерполяции (§4, п. 3.5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa

from aquabit_ai.config.manifest import PeriodMetadata
from aquabit_ai.preprocess.errors import PreprocessingFatalError
from aquabit_ai.preprocess.log import PreprocessingLogger


STAGE_NAME = "3.5_time_canonicalization"


def _parse_iso_to_tz(raw_iso: str, target_tz: ZoneInfo, file_name: str, row_idx: int) -> datetime:
    s = raw_iso.strip()
    candidate = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise PreprocessingFatalError(
            "INVALID_TIMESTAMP",
            f"Некорректная дата ISO 8601 '{raw_iso}' ({file_name}, строка {row_idx})",
            file=file_name,
            field="time_iso8601",
            examples=[{"row_number": row_idx, "raw_value": raw_iso}],
        ) from exc
    if dt.tzinfo is None:
        raise PreprocessingFatalError(
            "TIMESTAMP_WITHOUT_TZ",
            f"Отсутствует таймзона в '{raw_iso}' ({file_name}, строка {row_idx})",
            file=file_name,
            field="time_iso8601",
            examples=[{"row_number": row_idx, "raw_value": raw_iso}],
        )
    return dt.astimezone(target_tz)


def _extract_col_pylist_preserving_nan(series: pd.Series) -> tuple[list[Any], pa.DataType]:
    pa_arr = series.array._pa_array  # type: ignore[attr-defined]
    if isinstance(pa_arr, pa.ChunkedArray):
        pa_arr = pa_arr.combine_chunks()
    null_mask = pa_arr.is_null().to_pylist()
    raw_vals = pa_arr.to_pylist()
    out: list[Any] = [None if is_n else val for is_n, val in zip(null_mask, raw_vals)]
    return out, pa_arr.type


def canonicalize_timestamps(
    tables: dict[str, pd.DataFrame],
    period: PeriodMetadata | None,
    logger: PreprocessingLogger,
) -> tuple[dict[str, pd.DataFrame], dict[str, list[bool]]]:
    """Приводит time_iso8601 к таймзоне manifest.period.timezone, проверяет монотонность,
    шаг и вставляет явные null-строки на месте дыр временного ряда (без интерполяции!).

    Возвращает (обновлённые таблицы, словарь {file: row_level_timestamp_gap_flags}).
    """
    tz_name = period.timezone if period is not None else "UTC"
    target_tz = ZoneInfo(tz_name)
    step_s = period.step_seconds if period is not None else 3600

    out_tables: dict[str, pd.DataFrame] = {}
    table_gap_flags: dict[str, list[bool]] = {}

    for rel_path, df in sorted(tables.items()):
        if "time_iso8601" not in df.columns:
            out_tables[rel_path] = df
            continue

        if df.empty:
            out_tables[rel_path] = df
            table_gap_flags[rel_path] = []
            continue

        time_vals, _ = _extract_col_pylist_preserving_nan(df["time_iso8601"])
        parsed_dts: list[datetime | None] = []
        formatted_isos: list[str | None] = []
        tz_reformatted = 0

        for i, raw_t in enumerate(time_vals):
            if raw_t is None:
                parsed_dts.append(None)
                formatted_isos.append(None)
                continue
            dt = _parse_iso_to_tz(str(raw_t), target_tz, rel_path, i + 2)
            iso_out = dt.isoformat()
            if iso_out != str(raw_t):
                tz_reformatted += 1
            parsed_dts.append(dt)
            formatted_isos.append(iso_out)

        if tz_reformatted > 0:
            logger.record(
                stage=STAGE_NAME,
                operation="normalize_timezone_iso8601",
                file=rel_path,
                field="time_iso8601",
                after=tz_name,
                affected_rows=tz_reformatted,
                severity="info",
            )

        # Если таблица не является объектным временным рядом с 'id' — только обновляем колонку времени
        if "id" not in df.columns or not rel_path.startswith("timeseries/"):
            updated = df.copy()
            updated["time_iso8601"] = pd.Series(
                pd.arrays.ArrowExtensionArray(pa.array(formatted_isos, type=pa.string())),
                name="time_iso8601",
                index=df.index,
            )
            out_tables[rel_path] = updated
            table_gap_flags[rel_path] = [False] * len(updated)
            continue

        # Извлекаем все колонки в списки Python с сохранением типов Arrow (включая null vs NaN)
        col_data: dict[str, list[Any]] = {}
        col_types: dict[str, pa.DataType] = {}
        for col in df.columns:
            if col == "time_iso8601":
                col_data[col] = formatted_isos
                col_types[col] = pa.string()
            else:
                vals, pa_t = _extract_col_pylist_preserving_nan(df[col])
                col_data[col] = vals
                col_types[col] = pa_t

        # Группируем индексы строк по строковому object_id (в порядке появления объекта)
        obj_order: list[str] = []
        obj_rows: dict[str, list[int]] = {}
        for r_idx, oid in enumerate(col_data["id"]):
            key = "" if oid is None else str(oid)
            if key not in obj_rows:
                obj_order.append(key)
                obj_rows[key] = []
            obj_rows[key].append(r_idx)

        rebuilt_cols: dict[str, list[Any]] = {c: [] for c in df.columns}
        gap_flags: list[bool] = []
        non_monotonic_count = 0
        step_mismatch_count = 0
        inserted_gap_rows = 0

        for oid in obj_order:
            indices = obj_rows[oid]
            # Проверка монотонности
            dts_for_obj = [parsed_dts[i] for i in indices]
            for k in range(1, len(dts_for_obj)):
                prev_dt, cur_dt = dts_for_obj[k - 1], dts_for_obj[k]
                if prev_dt is not None and cur_dt is not None and cur_dt <= prev_dt:
                    non_monotonic_count += 1

            # Сортируем по времени при нарушении порядка (с явной записью в лог)
            sorted_indices = sorted(
                indices,
                key=lambda ix: (parsed_dts[ix] is None, parsed_dts[ix] or datetime.min),
            )

            prev_dt: datetime | None = None
            for ix in sorted_indices:
                cur_dt = parsed_dts[ix]
                if prev_dt is not None and cur_dt is not None:
                    delta_s = (cur_dt - prev_dt).total_seconds()
                    if delta_s != step_s:
                        # Если пропущено целое число шагов (и не более 1000 шагов) — вставляем явные null-строки!
                        if (
                            delta_s > step_s
                            and delta_s % step_s == 0
                            and int(delta_s // step_s) - 1 <= 1000
                        ):
                            n_missing = int(delta_s // step_s) - 1
                            for m_step in range(1, n_missing + 1):
                                gap_dt = prev_dt + timedelta(seconds=step_s * m_step)
                                for c in df.columns:
                                    if c == "id":
                                        rebuilt_cols[c].append(oid)
                                    elif c == "time_iso8601":
                                        rebuilt_cols[c].append(gap_dt.isoformat())
                                    else:
                                        # Строго null, никакой интерполяции (§3.5, §6)!
                                        rebuilt_cols[c].append(None)
                                gap_flags.append(True)
                                inserted_gap_rows += 1
                        else:
                            step_mismatch_count += 1

                for c in df.columns:
                    rebuilt_cols[c].append(col_data[c][ix])
                gap_flags.append(False)
                if cur_dt is not None:
                    prev_dt = cur_dt

        if non_monotonic_count > 0:
            logger.record(
                stage=STAGE_NAME,
                operation="non_monotonic_timestamps_sorted",
                file=rel_path,
                field="time_iso8601",
                affected_rows=non_monotonic_count,
                severity="warning",
            )
        if step_mismatch_count > 0:
            logger.record(
                stage=STAGE_NAME,
                operation="step_seconds_mismatch",
                file=rel_path,
                field="time_iso8601",
                before=f"expected_{step_s}s",
                after="irregular_delta",
                affected_rows=step_mismatch_count,
                severity="warning",
            )
        if inserted_gap_rows > 0:
            logger.record(
                stage=STAGE_NAME,
                operation="insert_null_rows_for_timestamp_gaps",
                file=rel_path,
                field="time_iso8601",
                affected_rows=inserted_gap_rows,
                severity="warning",
                details={"step_seconds": step_s, "interpolation": "forbidden_used_null"},
            )

        new_series_map: dict[str, pd.Series] = {}
        new_index = pd.RangeIndex(len(gap_flags))
        for c in df.columns:
            pa_t = col_types[c]
            arr = (
                pa.array(rebuilt_cols[c], type=pa_t, from_pandas=False)
                if pa.types.is_floating(pa_t)
                else pa.array(rebuilt_cols[c], type=pa_t)
            )
            new_series_map[c] = pd.Series(
                pd.arrays.ArrowExtensionArray(arr), name=c, index=new_index
            )

        out_tables[rel_path] = pd.DataFrame(new_series_map, index=new_index)
        table_gap_flags[rel_path] = gap_flags

    return out_tables, table_gap_flags
