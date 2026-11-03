"""Движок проверки файлов AquaBit на нулевые значения и очистки 4 целевых таблиц (ADR-0008).

Проверяет все 13 таблиц папки города на:
- точные нулевые значения (0, 0.0, 0.00) отдельно от пустых пропусков ("" -> null, Принцип 6);
- полностью нулевые строки (R0..R1439 == 0) и частично нулевые строки в широких матрицах;
- 24-часовую полноту графиков потребления (по 24 строки на каждый t* ID);
- буквенные префиксы классов объектов (c, e, p, v, u, t);
- норматив требуемого давления (10 м для 1 этажа + 4 м на каждый следующий этаж, СП 31.13330.2021).

При включённой очистке удаляет нулевые строки строго в 4 таблицах:
1. Поток Насос.csv       — строки, где все R0..R1439 равны 0 (закрытые/резервные насосы);
2. Потребители Узел.csv  — строки, где Потребление == 0 (или не указано);
3. Потребление Узел.csv  — строки, где все R0..R1439 равны 0 (промежуточные узлы без водоразбора);
4. Узел.csv              — строки, где Требуемое давление не указано (пусто или <= 0).
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field as dc_field
from pathlib import Path
from typing import Any

import numpy as np

from aquabit_ai.config.csv_contracts import AliasRegistry, get_contract_for_path
from aquabit_ai.ingest.archive import IGNORED_ARCHIVE_ENTRIES, _detect_csv_delimiter, _detect_encoding_raw
from aquabit_ai.ingest.city_folder import (
    discover_city_directories,
    read_wide_timeseries_file,
    resolve_city_csv_route,
)


NULL_STRINGS = {"", "null", "NULL", "None"}

# Четыре целевые таблицы для удаления нулевых строк (по прямому требованию пользователя)
ZERO_CLEAN_TARGET_ROUTES: frozenset[str] = frozenset(
    {
        "wide/pump_flow.csv",   # Поток Насос.csv
        "demands.csv",          # Потребители Узел.csv
        "wide/node_demand.csv", # Потребление Узел.csv
        "nodes.csv",            # Узел.csv (где Требуемое давление не указано / 0)
    }
)


def infer_floors_from_required_pressure(pressure_m: float) -> str:
    """Интерпретирует требуемое давление по отечественной формуле H = 10 + 4*(n - 1) м."""
    if pressure_m <= 0.0:
        return "0 м (промежуточный узел без абонентов)"
    if pressure_m < 10.0:
        return f"<10 м ({pressure_m:g} м — ниже минимума 1 этажа!)"
    diff = pressure_m - 10.0
    if abs(diff - round(diff / 4.0) * 4.0) < 1e-6:
        floors = 1 + int(round(diff / 4.0))
        return f"{floors} эт. ({pressure_m:g} м)"
    approx_floors = 1.0 + diff / 4.0
    return f"нестанд. {pressure_m:g} м (~{approx_floors:.1f} эт.)"


@dataclass
class ColumnZeroStat:
    """Статистика нулей и пропусков по одной колонке статической таблицы."""

    column_name: str
    canonical_name: str | None
    total_rows: int
    zero_count: int
    zero_pct: float
    null_count: int
    null_pct: float
    negative_count: int
    note: str = ""


@dataclass
class TableZeroAuditResult:
    """Результат проверки и (опционально) очистки одной CSV-таблицы города."""

    source_file: str
    canonical_route: str
    is_wide_timeseries: bool
    is_clean_target: bool
    rows_before: int
    rows_after: int
    rows_removed: int
    rows_removed_pct: float
    size_bytes_before: int
    size_bytes_after: int
    bytes_saved: int

    # Метрики нулей для широких матриц R0..R1439 и статических колонок
    all_zero_rows_count: int = 0
    all_zero_rows_pct: float = 0.0
    partial_zero_rows_count: int = 0
    zero_cells_count: int = 0
    zero_cells_pct: float = 0.0
    null_cells_count: int = 0
    removed_id_examples: list[str] = dc_field(default_factory=list)
    kept_partial_zero_id_examples: list[str] = dc_field(default_factory=list)
    column_stats: list[ColumnZeroStat] = dc_field(default_factory=list)
    cleaning_rule_applied: str = "Без удаления (только аудит)"
    warnings: list[str] = dc_field(default_factory=list)


@dataclass
class CityZeroAuditResult:
    """Сводный результат проверки нулей и очистки по одному городу."""

    city_name: str
    source_dir: str
    cleaned_dir: str | None
    elapsed_ms: float
    size_bytes_before: int
    size_bytes_after: int
    bytes_saved: int
    bytes_saved_pct: float
    total_rows_removed: int
    pruned_transit_nodes_count: int
    pruned_standby_pumps_count: int
    pruned_zero_consumers_count: int
    pruned_zero_demand_matrix_rows_count: int
    floor_distribution_by_required_pressure: dict[str, int] = dc_field(default_factory=dict)
    schedule_non_24h_ids: dict[str, int] = dc_field(default_factory=dict)
    id_prefix_violations_count: int = 0
    tables: list[TableZeroAuditResult] = dc_field(default_factory=list)


@dataclass
class CorpusZeroAuditResult:
    """Сводный отчёт проверки и очистки нулей по всем папкам городов в data/."""

    mode: str  # "audit_only" | "clean_zeros"
    cities_count: int
    size_bytes_before: int
    size_bytes_after: int
    bytes_saved: int
    bytes_saved_pct: float
    total_rows_removed: int
    cities: list[CityZeroAuditResult] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _filter_csv_file_by_row_mask(
    src_file: Path,
    dst_file: Path,
    keep_row_mask: list[bool] | np.ndarray,
    encoding: str,
    has_bom: bool,
) -> int:
    """Потоково переписывает CSV, сохраняя заголовок и только строки с keep_row_mask[i] == True.

    Не переформатирует числа и строковые ID — сохраняет 100% исходное представление строк!
    Возвращает размер записанного файла в байтах.
    """
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    read_enc = "utf-8-sig" if (encoding in {"utf-8", "utf-8-sig"} and has_bom) else encoding
    write_enc = "utf-8-sig" if has_bom else ("utf-8" if encoding == "utf-8-sig" else encoding)

    with src_file.open("r", encoding=read_enc, newline="") as fin, dst_file.open(
        "w", encoding=write_enc, newline=""
    ) as fout:
        header_written = False
        data_idx = 0
        n_mask = len(keep_row_mask)
        for raw_line in fin:
            if not raw_line.strip():
                continue
            if not header_written:
                fout.write(raw_line)
                header_written = True
                continue
            if data_idx < n_mask and bool(keep_row_mask[data_idx]):
                fout.write(raw_line)
            data_idx += 1

    return dst_file.stat().st_size


def _parse_float_or_kind(cell: str) -> tuple[str, float]:
    """Классифицирует строковую ячейку: ('null', 0.0) | ('num', val) | ('str', 0.0)."""
    s = cell.strip()
    if s in NULL_STRINGS:
        return ("null", 0.0)
    try:
        v = float(s)
        if np.isnan(v):
            return ("nan", 0.0)
        return ("num", v)
    except ValueError:
        return ("str", 0.0)


def _check_city_id_prefix(canonical_route: str, canonical_col: str | None, raw_val: str) -> bool:
    """Возвращает True, если строковый ID соответствует классу объекта (c, e, p, v, u, t)."""
    s = raw_val.strip()
    if s in NULL_STRINGS:
        return True
    expected_map: dict[tuple[str, str], tuple[str, ...]] = {
        ("nodes.csv", "id"): ("c",),
        ("pipes.csv", "id"): ("e",),
        ("sources.csv", "id"): ("e", "c"),
        ("pumps.csv", "id"): ("p",),
        ("pumps.csv", "curve_id"): ("u",),
        ("valves.csv", "id"): ("v",),
        ("pump_curves.csv", "curve_id"): ("u",),
        ("irregularity_curves.csv", "curve_id"): ("t",),
        ("demands.csv", "node_id"): ("c",),
        ("demands.csv", "curve_id"): ("t",),
        ("wide/node_head.csv", "id"): ("c", "e"),
        ("wide/node_demand.csv", "id"): ("c",),
        ("wide/pipe_flow.csv", "id"): ("e",),
        ("wide/pump_flow.csv", "id"): ("p",),
        ("wide/valve_flow.csv", "id"): ("v",),
    }
    if canonical_col is None:
        return True
    allowed = expected_map.get((canonical_route, canonical_col))
    if allowed is None:
        return True
    return any(s.startswith(pfx) for pfx in allowed)


def _process_wide_table_zeros(
    entry: Path,
    canonical_route: str,
    dst_file: Path | None,
    *,
    perform_clean: bool,
    extra_drop_ids: set[str] | None = None,
) -> tuple[TableZeroAuditResult, list[str], int]:
    """Проверяет широкую матрицу R0..R1439 на нули и при необходимости фильтрует нулевые строки."""
    ingested = read_wide_timeseries_file(entry, canonical_route)
    size_before = entry.stat().st_size

    if ingested.wide_matrix is None:
        # Резервная ветка на случай нестандартного файла
        if dst_file is not None and entry.resolve() != dst_file.resolve():
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, dst_file)
        return (
            TableZeroAuditResult(
                source_file=entry.name,
                canonical_route=canonical_route,
                is_wide_timeseries=True,
                is_clean_target=canonical_route in ZERO_CLEAN_TARGET_ROUTES,
                rows_before=0,
                rows_after=0,
                rows_removed=0,
                rows_removed_pct=0.0,
                size_bytes_before=size_before,
                size_bytes_after=size_before,
                bytes_saved=0,
                warnings=[ingested.parse_error or "Не удалось прочитать широкую матрицу"],
            ),
            [],
            0,
        )

    w = ingested.wide_matrix
    n_rows = w.num_rows
    n_steps = w.n_steps
    total_cells = max(1, n_rows * n_steps)
    ids = w.id_list()

    pfx_bad = sum(
        0 if (oid is None or _check_city_id_prefix(canonical_route, "id", oid)) else 1
        for oid in ids
    )

    mat, null_mask = w.to_numpy_with_null_mask()
    ieee_nan = (~null_mask) & np.isnan(mat)
    valid = (~null_mask) & (~ieee_nan)

    null_cells = int(np.count_nonzero(null_mask))
    zero_mask = valid & (mat == 0.0)
    zero_cells = int(np.count_nonzero(zero_mask))
    zero_cells_pct = round(100.0 * zero_cells / total_cells, 2)

    if n_rows > 0 and n_steps > 0:
        valid_counts = np.sum(valid, axis=1)
        all_zero_mask = (valid_counts > 0) & np.all(zero_mask | (~valid), axis=1) & (null_mask.sum(axis=1) == 0)
        partial_zero_mask = (~all_zero_mask) & np.any(zero_mask, axis=1) & np.any(valid & (mat != 0.0), axis=1)
    else:
        all_zero_mask = np.zeros(n_rows, dtype=bool)
        partial_zero_mask = np.zeros(n_rows, dtype=bool)

    all_zero_n = int(np.count_nonzero(all_zero_mask))
    all_zero_pct = round(100.0 * all_zero_n / n_rows, 2) if n_rows > 0 else 0.0
    partial_zero_n = int(np.count_nonzero(partial_zero_mask))

    kept_partial_examples = [
        str(ids[i]) for i in np.flatnonzero(partial_zero_mask)[:15] if ids[i] is not None
    ]

    is_target = canonical_route in {"wide/pump_flow.csv", "wide/node_demand.csv"} or (
        canonical_route == "wide/node_head.csv" and bool(extra_drop_ids)
    )

    drop_mask = np.zeros(n_rows, dtype=bool)
    rule_desc = "Без удаления (только аудит нулей)"
    if canonical_route == "wide/pump_flow.csv":
        rule_desc = "Удаление строк, где все шаги R0..R1439 == 0 (выключенные/резервные насосы)"
        if perform_clean:
            drop_mask = all_zero_mask
    elif canonical_route == "wide/node_demand.csv":
        rule_desc = "Удаление строк, где все шаги R0..R1439 == 0 (промежуточные узлы без потребления)"
        if perform_clean:
            drop_mask = all_zero_mask
    elif canonical_route == "wide/node_head.csv" and extra_drop_ids:
        rule_desc = "Синхронное удаление отфильтрованных промежуточных узлов (--prune-node-head)"
        if perform_clean:
            drop_mask = np.array([(oid in extra_drop_ids) for oid in ids], dtype=bool)

    removed_ids = [
        str(ids[i])
        for i in np.flatnonzero(drop_mask if perform_clean else all_zero_mask)
        if ids[i] is not None
    ]

    rows_removed = int(np.count_nonzero(drop_mask)) if perform_clean else 0
    rows_after = n_rows - rows_removed
    size_after = size_before

    if dst_file is not None:
        if perform_clean and rows_removed > 0:
            keep_mask = ~drop_mask
            if entry.resolve() == dst_file.resolve():
                tmp_dst = dst_file.with_suffix(".csv.tmp_clean")
                size_after = _filter_csv_file_by_row_mask(
                    entry,
                    tmp_dst,
                    keep_mask,
                    ingested.detected_encoding or "utf-8",
                    ingested.has_bom,
                )
                tmp_dst.replace(dst_file)
            else:
                size_after = _filter_csv_file_by_row_mask(
                    entry,
                    dst_file,
                    keep_mask,
                    ingested.detected_encoding or "utf-8",
                    ingested.has_bom,
                )
        elif entry.resolve() != dst_file.resolve():
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, dst_file)
            size_after = dst_file.stat().st_size

    warnings_list: list[str] = []
    if null_cells > 0:
        warnings_list.append(
            f"Обнаружено {null_cells} пустых (null) ячеек — сохранены без замены на 0 (Принцип 6)"
        )
    if partial_zero_n > 0 and canonical_route == "wide/pump_flow.csv":
        warnings_list.append(
            f"{partial_zero_n} насосов имеют нули только на части суток (периодическая работа) — сохранены!"
        )

    return (
        TableZeroAuditResult(
            source_file=entry.name,
            canonical_route=canonical_route,
            is_wide_timeseries=True,
            is_clean_target=is_target,
            rows_before=n_rows,
            rows_after=rows_after,
            rows_removed=rows_removed,
            rows_removed_pct=round(100.0 * rows_removed / n_rows, 2) if n_rows > 0 else 0.0,
            size_bytes_before=size_before,
            size_bytes_after=size_after,
            bytes_saved=max(0, size_before - size_after),
            all_zero_rows_count=all_zero_n,
            all_zero_rows_pct=all_zero_pct,
            partial_zero_rows_count=partial_zero_n,
            zero_cells_count=zero_cells,
            zero_cells_pct=zero_cells_pct,
            null_cells_count=null_cells,
            removed_id_examples=removed_ids[:20],
            kept_partial_zero_id_examples=kept_partial_examples,
            cleaning_rule_applied=rule_desc,
            warnings=warnings_list,
        ),
        removed_ids if (perform_clean or is_target) else [],
        pfx_bad,
    )


def _process_static_table_zeros(
    entry: Path,
    canonical_route: str,
    dst_file: Path | None,
    registry: AliasRegistry,
    *,
    perform_clean: bool,
) -> tuple[
    TableZeroAuditResult,
    list[str],
    dict[str, int],
    dict[str, int],
    int,
]:
    """Проверяет статическую CSV-таблицу на нули и очищает Узел.csv / Потребители Узел.csv."""
    raw_bytes = entry.read_bytes()
    size_before = len(raw_bytes)
    enc, has_bom, text, _ = _detect_encoding_raw(raw_bytes)

    if text is None or not text.strip():
        if dst_file is not None and entry.resolve() != dst_file.resolve():
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, dst_file)
        return (
            TableZeroAuditResult(
                source_file=entry.name,
                canonical_route=canonical_route,
                is_wide_timeseries=False,
                is_clean_target=canonical_route in ZERO_CLEAN_TARGET_ROUTES,
                rows_before=0,
                rows_after=0,
                rows_removed=0,
                rows_removed_pct=0.0,
                size_bytes_before=size_before,
                size_bytes_after=size_before,
                bytes_saved=0,
            ),
            [],
            {},
            {},
            0,
        )

    delimiter = _detect_csv_delimiter(text)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    headers = rows[0] if rows else []
    data_rows = rows[1:] if len(rows) > 1 else []
    n_rows = len(data_rows)

    contract = get_contract_for_path(canonical_route)
    resolved = registry.resolve_table_headers(headers, contract)

    # Поколоночная статистика нулей и пропусков
    col_stats: list[ColumnZeroStat] = []
    pfx_bad = 0
    for col_idx, raw_h in enumerate(headers):
        can_h = resolved.get(raw_h)
        z_cnt = 0
        n_cnt = 0
        neg_cnt = 0
        for r in data_rows:
            cell = r[col_idx] if col_idx < len(r) else ""
            if not _check_city_id_prefix(canonical_route, can_h, cell):
                pfx_bad += 1
            kind, val = _parse_float_or_kind(cell)
            if kind == "null":
                n_cnt += 1
            elif kind == "num":
                if val == 0.0:
                    z_cnt += 1
                elif val < 0.0:
                    neg_cnt += 1

        note = ""
        if canonical_route == "nodes.csv" and can_h == "required_pressure_m" and (z_cnt + n_cnt) > 0:
            note = "Промежуточные узлы без заданного требуемого давления (подлежат удалению)"
        elif canonical_route == "nodes.csv" and can_h == "elevation_m" and z_cnt > 0:
            note = "Отметка 0.0 м над уровнем сравнения (НЕ удаляется при Требуемое давление > 0)"
        elif canonical_route == "demands.csv" and can_h == "base_demand_m3_h" and (z_cnt + n_cnt) > 0:
            note = "Нулевое базовое потребление абонента (подлежит удалению)"
        elif canonical_route == "pipes.csv" and can_h in {"diameter_mm", "length_m"} and z_cnt > 0:
            note = "ОШИБКА ГЕОМЕТРИИ: нулевой диаметр или длина участка!"
        elif canonical_route == "pipes.csv" and can_h == "minor_loss_coeff" and z_cnt > 0:
            note = "Штатный коэффициент местных потерь k = 0 (НЕ удаляется)"
        elif canonical_route == "pump_curves.csv" and can_h == "flow_m3_h" and z_cnt > 0:
            note = "Штатная точка напора холостого хода насоса Q = 0, H = H0 (НЕ удаляется!)"

        col_stats.append(
            ColumnZeroStat(
                column_name=raw_h,
                canonical_name=can_h,
                total_rows=n_rows,
                zero_count=z_cnt,
                zero_pct=round(100.0 * z_cnt / n_rows, 2) if n_rows > 0 else 0.0,
                null_count=n_cnt,
                null_pct=round(100.0 * n_cnt / n_rows, 2) if n_rows > 0 else 0.0,
                negative_count=neg_cnt,
                note=note,
            )
        )

    floor_dist: Counter[str] = Counter()
    non_24_schedules: dict[str, int] = {}
    warnings_list: list[str] = []
    drop_mask = [False] * n_rows
    candidate_drop_ids: list[str] = []
    rule_desc = "Без удаления (только аудит нулей)"

    # 1. Специальная логика для Узел.csv (удаляем там, где Требуемое давление не указано / <= 0)
    if canonical_route == "nodes.csv":
        rule_desc = "Удаление узлов, где 'Требуемое давление' не указано (пусто или <= 0)"
        id_idx = next((i for i, h in enumerate(headers) if resolved.get(h) == "id"), 0)
        req_idx = next(
            (i for i, h in enumerate(headers) if resolved.get(h) == "required_pressure_m"),
            None,
        )
        if req_idx is not None:
            for r_i, r in enumerate(data_rows):
                nid = r[id_idx].strip() if id_idx < len(r) else ""
                cell = r[req_idx] if req_idx < len(r) else ""
                kind, val = _parse_float_or_kind(cell)
                if kind == "null" or (kind == "num" and val <= 0.0):
                    candidate_drop_ids.append(nid)
                    if perform_clean:
                        drop_mask[r_i] = True
                elif kind == "num":
                    label = infer_floors_from_required_pressure(val)
                    floor_dist[label] += 1
                    if val < 10.0:
                        warnings_list.append(
                            f"Узел {nid}: Требуемое давление = {val:g} м (< 10 м для 1-эт. застройки!)"
                        )
        else:
            warnings_list.append("В Узел.csv не найдена колонка 'Требуемое давление'")

    # 2. Специальная логика для Потребители Узел.csv (удаляем строки с Потребление == 0 или пусто)
    elif canonical_route == "demands.csv":
        rule_desc = "Удаление записей абонентов, где 'Потребление' == 0 или пусто"
        id_idx = next((i for i, h in enumerate(headers) if resolved.get(h) == "node_id"), 0)
        q_idx = next(
            (i for i, h in enumerate(headers) if resolved.get(h) == "base_demand_m3_h"),
            None,
        )
        if q_idx is not None:
            for r_i, r in enumerate(data_rows):
                nid = r[id_idx].strip() if id_idx < len(r) else ""
                cell = r[q_idx] if q_idx < len(r) else ""
                kind, val = _parse_float_or_kind(cell)
                if kind == "null" or (kind == "num" and val == 0.0):
                    candidate_drop_ids.append(nid)
                    if perform_clean:
                        drop_mask[r_i] = True

    # 3. Проверка 24 точек на каждый ID в График потребления.csv
    elif canonical_route == "irregularity_curves.csv":
        cid_idx = next((i for i, h in enumerate(headers) if resolved.get(h) == "curve_id"), 0)
        sched_counts: Counter[str] = Counter()
        for r in data_rows:
            cid = r[cid_idx].strip() if cid_idx < len(r) else ""
            if cid not in NULL_STRINGS:
                sched_counts[cid] += 1
        non_24_schedules = {cid: cnt for cid, cnt in sorted(sched_counts.items()) if cnt != 24}
        if non_24_schedules:
            warnings_list.append(
                f"Графики с количеством строк != 24 ч: {len(non_24_schedules)} шт. ({list(non_24_schedules.items())[:5]})"
            )

    # 4. Проверка геометрических нулей в Труба.csv
    elif canonical_route == "pipes.csv":
        for st in col_stats:
            if st.canonical_name in {"diameter_mm", "length_m"} and st.zero_count > 0:
                warnings_list.append(
                    f"КРИТИЧНО: в колонке '{st.column_name}' найдено {st.zero_count} нулевых значений!"
                )

    rows_removed = sum(1 for x in drop_mask if x) if perform_clean else 0
    rows_after = n_rows - rows_removed
    size_after = size_before

    if dst_file is not None:
        if perform_clean and rows_removed > 0:
            keep_mask = [not d for d in drop_mask]
            if entry.resolve() == dst_file.resolve():
                tmp_dst = dst_file.with_suffix(".csv.tmp_clean")
                size_after = _filter_csv_file_by_row_mask(
                    entry, tmp_dst, keep_mask, enc or "utf-8", has_bom
                )
                tmp_dst.replace(dst_file)
            else:
                size_after = _filter_csv_file_by_row_mask(
                    entry, dst_file, keep_mask, enc or "utf-8", has_bom
                )
        elif entry.resolve() != dst_file.resolve():
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, dst_file)
            size_after = dst_file.stat().st_size

    total_zero_cells = sum(s.zero_count for s in col_stats)
    total_null_cells = sum(s.null_count for s in col_stats)
    denom = max(1, n_rows * max(1, len(headers)))

    return (
        TableZeroAuditResult(
            source_file=entry.name,
            canonical_route=canonical_route,
            is_wide_timeseries=False,
            is_clean_target=canonical_route in ZERO_CLEAN_TARGET_ROUTES,
            rows_before=n_rows,
            rows_after=rows_after,
            rows_removed=rows_removed,
            rows_removed_pct=round(100.0 * rows_removed / n_rows, 2) if n_rows > 0 else 0.0,
            size_bytes_before=size_before,
            size_bytes_after=size_after,
            bytes_saved=max(0, size_before - size_after),
            all_zero_rows_count=len(candidate_drop_ids),
            all_zero_rows_pct=round(100.0 * len(candidate_drop_ids) / n_rows, 2) if n_rows > 0 else 0.0,
            zero_cells_count=total_zero_cells,
            zero_cells_pct=round(100.0 * total_zero_cells / denom, 2),
            null_cells_count=total_null_cells,
            removed_id_examples=candidate_drop_ids[:20],
            column_stats=col_stats,
            cleaning_rule_applied=rule_desc,
            warnings=warnings_list[:15],
        ),
        candidate_drop_ids,
        dict(floor_dist),
        non_24_schedules,
        pfx_bad,
    )


def audit_and_clean_single_city(
    city_dir: Path,
    *,
    cleaned_city_dir: Path | None = None,
    perform_clean: bool = False,
    prune_node_head: bool = False,
    registry: AliasRegistry | None = None,
) -> CityZeroAuditResult:
    """Выполняет полный аудит нулей по всем файлам одного города и (опционально) очистку 4 таблиц."""
    t0 = time.perf_counter()
    reg = registry or AliasRegistry.from_yaml()
    city_name = unicodedata.normalize("NFC", city_dir.name)

    entries = sorted(
        [p for p in city_dir.iterdir() if p.is_file() and p.name not in IGNORED_ARCHIVE_ENTRIES],
        key=lambda p: unicodedata.normalize("NFC", p.name).lower(),
    )

    # Сначала обрабатываем Узел.csv, чтобы знать точный список промежуточных узлов без требуемого давления
    route_entries: list[tuple[Path, str | None]] = [
        (e, resolve_city_csv_route(e)) for e in entries
    ]
    route_entries.sort(key=lambda pair: (0 if pair[1] == "nodes.csv" else 1, pair[0].name.lower()))

    table_results: list[TableZeroAuditResult] = []
    pruned_transit_nodes: list[str] = []
    pruned_standby_pumps: list[str] = []
    pruned_zero_consumers = 0
    pruned_zero_demand_rows = 0
    floor_dist_city: dict[str, int] = {}
    schedule_non_24_city: dict[str, int] = {}
    total_pfx_violations = 0

    for entry, route in route_entries:
        dst_file = (cleaned_city_dir / entry.name) if (perform_clean and cleaned_city_dir is not None) else None

        if route is None:
            # Копируем manifest.json и прочие служебные файлы без изменений
            if dst_file is not None and entry.resolve() != dst_file.resolve() and entry.name != "pruned_zero_manifest.json":
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, dst_file)
            continue

        contract = get_contract_for_path(route)
        if contract is not None and contract.is_wide_timeseries:
            extra_drop = (
                set(pruned_transit_nodes)
                if (prune_node_head and route == "wide/node_head.csv")
                else None
            )
            t_res, dropped_ids, pfx_bad = _process_wide_table_zeros(
                entry,
                route,
                dst_file,
                perform_clean=perform_clean,
                extra_drop_ids=extra_drop,
            )
            total_pfx_violations += pfx_bad
            if route == "wide/pump_flow.csv":
                pruned_standby_pumps = dropped_ids
            elif route == "wide/node_demand.csv":
                pruned_zero_demand_rows = len(dropped_ids)
            table_results.append(t_res)
        else:
            t_res, dropped_ids, fl_dist, non_24, pfx_bad = _process_static_table_zeros(
                entry,
                route,
                dst_file,
                reg,
                perform_clean=perform_clean,
            )
            total_pfx_violations += pfx_bad
            if route == "nodes.csv":
                pruned_transit_nodes = dropped_ids
                floor_dist_city = fl_dist
            elif route == "demands.csv":
                pruned_zero_consumers = len(dropped_ids)
            elif route == "irregularity_curves.csv":
                schedule_non_24_city = non_24
            table_results.append(t_res)

    # Записываем манифест удалённых транзитных узлов и резервных насосов для сохранения ссылочной целостности
    if perform_clean and cleaned_city_dir is not None:
        cleaned_city_dir.mkdir(parents=True, exist_ok=True)
        manifest_payload = {
            "city_name": city_name,
            "cleaned_tables": [
                "Поток Насос.csv",
                "Потребители Узел.csv",
                "Потребление Узел.csv",
                "Узел.csv",
            ]
            + (["Напор Узел.csv"] if prune_node_head else []),
            "pruned_transit_node_ids": pruned_transit_nodes,
            "pruned_standby_pump_ids": pruned_standby_pumps,
            "pruned_zero_consumers_count": pruned_zero_consumers,
            "pruned_zero_demand_matrix_rows_count": pruned_zero_demand_rows,
        }
        (cleaned_city_dir / "pruned_zero_manifest.json").write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    table_results.sort(key=lambda r: (not r.is_clean_target, -r.size_bytes_before, r.source_file))
    bytes_before = sum(t.size_bytes_before for t in table_results)
    bytes_after = sum(t.size_bytes_after for t in table_results)
    saved = max(0, bytes_before - bytes_after)
    saved_pct = round(100.0 * saved / bytes_before, 2) if bytes_before > 0 else 0.0
    total_removed = sum(t.rows_removed for t in table_results)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    return CityZeroAuditResult(
        city_name=city_name,
        source_dir=str(city_dir),
        cleaned_dir=str(cleaned_city_dir) if (perform_clean and cleaned_city_dir) else None,
        elapsed_ms=elapsed_ms,
        size_bytes_before=bytes_before,
        size_bytes_after=bytes_after,
        bytes_saved=saved,
        bytes_saved_pct=saved_pct,
        total_rows_removed=total_removed,
        pruned_transit_nodes_count=len(pruned_transit_nodes),
        pruned_standby_pumps_count=len(pruned_standby_pumps),
        pruned_zero_consumers_count=pruned_zero_consumers,
        pruned_zero_demand_matrix_rows_count=pruned_zero_demand_rows,
        floor_distribution_by_required_pressure=floor_dist_city,
        schedule_non_24h_ids=schedule_non_24_city,
        id_prefix_violations_count=total_pfx_violations,
        tables=table_results,
    )


def audit_and_clean_zeros(
    target_path: str | Path,
    *,
    cleaned_output_root: str | Path | None = None,
    perform_clean: bool = False,
    in_place: bool = False,
    prune_node_head: bool = False,
) -> CorpusZeroAuditResult:
    """Пакетно проверяет нулевые значения и (при perform_clean=True) очищает 4 таблицы во всех городах."""
    root = Path(target_path)
    city_dirs = discover_city_directories(root)
    if not city_dirs:
        raise FileNotFoundError(
            f"По пути '{root}' не найдено папок городов AquaBit с CSV-таблицами."
        )

    is_single_city = len(city_dirs) == 1 and city_dirs[0].resolve() == root.resolve()
    out_base = Path(cleaned_output_root) if cleaned_output_root is not None else None
    reg = AliasRegistry.from_yaml()

    city_results: list[CityZeroAuditResult] = []
    for cdir in city_dirs:
        if perform_clean:
            if in_place:
                dst_dir: Path | None = cdir
            elif out_base is not None:
                dst_dir = out_base if is_single_city else (out_base / cdir.name)
            else:
                dst_dir = cdir.parent / f"{cdir.name}_cleaned"
        else:
            dst_dir = None

        city_results.append(
            audit_and_clean_single_city(
                cdir,
                cleaned_city_dir=dst_dir,
                perform_clean=perform_clean,
                prune_node_head=prune_node_head,
                registry=reg,
            )
        )

    tot_before = sum(c.size_bytes_before for c in city_results)
    tot_after = sum(c.size_bytes_after for c in city_results)
    tot_saved = max(0, tot_before - tot_after)
    tot_saved_pct = round(100.0 * tot_saved / tot_before, 2) if tot_before > 0 else 0.0
    tot_removed = sum(c.total_rows_removed for c in city_results)

    return CorpusZeroAuditResult(
        mode="clean_zeros" if perform_clean else "audit_only",
        cities_count=len(city_results),
        size_bytes_before=tot_before,
        size_bytes_after=tot_after,
        bytes_saved=tot_saved,
        bytes_saved_pct=tot_saved_pct,
        total_rows_removed=tot_removed,
        cities=city_results,
    )
