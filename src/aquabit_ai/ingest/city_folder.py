"""Адаптер папок городов AquaBit (13 отдельных CSV с широкими матрицами R0..R1439, ADR-0007).

Оптимизирован для больших файлов (десятки тысяч объектов × 1 440 шагов):
- широкие таблицы (Напор Узел, Потребление Узел, Поток Труба/Клапан/Насос) читаются
  многопоточным C++-парсером pyarrow.csv.read_csv напрямую в типизированные буферы Arrow
  (ID -> string, R0..R{T-1} -> float64 с разделением null vs 0.0 vs IEEE NaN);
- статические справочники читаются без автотипизации с поддержкой многострочных кривых
  (Кривая QH, График потребления) и нескольких потребителей на один узел (Потребители Узел).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
from pydantic import ValidationError

from aquabit_ai.config.csv_contracts import WIDE_STEP_HEADER_RE, get_contract_for_path
from aquabit_ai.config.manifest import ManifestSchema, RawFileSnapshot
from aquabit_ai.config.validation_models import CheckCode, ValidationCheckItem
from aquabit_ai.ingest.archive import (
    IGNORED_ARCHIVE_ENTRIES,
    IngestedCSVTable,
    IngestionBundle,
    _detect_csv_delimiter,
    _detect_encoding_raw,
    _read_raw_csv_bytes,
    generate_run_id,
)


NULL_TOKENS_LIST = ["", "null", "NULL", "None"]
NAN_TOKENS_SET = {"NaN", "nan", "NAN"}


def _normalize_stem(filename: str) -> str:
    """Приводит имя файла без расширения к каноническому NFC нижнему регистру."""
    nfc = unicodedata.normalize("NFC", filename).strip()
    if nfc.lower().endswith(".csv"):
        nfc = nfc[:-4]
    nfc = nfc.replace("_", " ").replace("ё", "е").replace("Ё", "Е")
    nfc = re.sub(r"\s+", " ", nfc).strip().lower()
    return nfc


# Отображение нормализованных русских/канонических имён файлов на внутренние контракты
CITY_TABLE_STEM_MAP: dict[str, str] = {
    # Статические таблицы топологии и справочников
    "узел": "nodes.csv",
    "узлы": "nodes.csv",
    "nodes": "nodes.csv",
    "труба": "pipes.csv",
    "трубы": "pipes.csv",
    "участки": "pipes.csv",
    "pipes": "pipes.csv",
    "источники": "sources.csv",
    "источник": "sources.csv",
    "sources": "sources.csv",
    "резервуар": "reservoirs.csv",
    "резервуары": "reservoirs.csv",
    "reservoirs": "reservoirs.csv",
    "клапан": "valves.csv",
    "клапаны": "valves.csv",
    "арматура": "valves.csv",
    "valves": "valves.csv",
    "насос": "pumps.csv",
    "насосы": "pumps.csv",
    "pumps": "pumps.csv",
    "кривая qh": "pump_curves.csv",
    "кривые qh": "pump_curves.csv",
    "pump curves": "pump_curves.csv",
    "потребители узел": "demands.csv",
    "потребители узла": "demands.csv",
    "потребители": "demands.csv",
    "demands": "demands.csv",
    "график потребления": "irregularity_curves.csv",
    "графики потребления": "irregularity_curves.csv",
    "irregularity curves": "irregularity_curves.csv",
    # Широкие динамические матрицы R0..R{T-1}
    "напор узел": "wide/node_head.csv",
    "напоры узел": "wide/node_head.csv",
    "потребление узел": "wide/node_demand.csv",
    "поток труба": "wide/pipe_flow.csv",
    "поток клапан": "wide/valve_flow.csv",
    "поток насос": "wide/pump_flow.csv",
    "скорость труба": "wide/pipe_velocity.csv",
    "уровень резервуар": "wide/reservoir_level.csv",
    "напор насос": "wide/pump_head.csv",
}

MANDATORY_CITY_TABLES: tuple[str, ...] = (
    "nodes.csv",
    "pipes.csv",
    "sources.csv",
)


@dataclass
class WideTimeseriesMatrix:
    """Типизированное представление широкой матрицы ID,R0..R{T-1} в памяти PyArrow."""

    source_filename: str
    canonical_path: str
    canonical_metric: str
    target_entity_type: str
    id_column_raw: str
    step_columns: list[str]
    step_indices: list[int]
    step_seconds: int
    arrow_table: pa.Table
    parse_time_ms: float

    @property
    def num_rows(self) -> int:
        return self.arrow_table.num_rows

    @property
    def n_steps(self) -> int:
        return len(self.step_columns)

    def id_list(self) -> list[str | None]:
        """Возвращает список строковых ID объектов с сохранением null."""
        col = self.arrow_table.column(self.id_column_raw).combine_chunks()
        return [
            None if is_null else str(val)
            for is_null, val in zip(col.is_null().to_pylist(), col.to_pylist())
        ]

    def to_numpy_with_null_mask(self) -> tuple[np.ndarray, np.ndarray]:
        """Возвращает (values_float64[N, T], null_mask_bool[N, T]).

        В values_float64 ячейки Arrow null временно кодируются как np.nan для быстрых
        векторизованных операций, а точное различие null vs IEEE NaN хранится в null_mask!
        """
        n_rows = self.num_rows
        n_steps = self.n_steps
        if n_rows == 0 or n_steps == 0:
            return (
                np.empty((n_rows, n_steps), dtype=np.float64),
                np.zeros((n_rows, n_steps), dtype=bool),
            )

        mat = np.empty((n_rows, n_steps), dtype=np.float64)
        null_mask = np.zeros((n_rows, n_steps), dtype=bool)

        for j, col_name in enumerate(self.step_columns):
            chunked = self.arrow_table.column(col_name)
            arr = chunked.combine_chunks() if chunked.num_chunks > 1 else (
                chunked.chunk(0) if chunked.num_chunks == 1 else pa.array([], type=pa.float64())
            )
            if arr.null_count == 0:
                mat[:, j] = arr.to_numpy(zero_copy_only=False)
            else:
                is_n = arr.is_null().to_numpy(zero_copy_only=False)
                null_mask[:, j] = is_n
                vals = arr.to_numpy(zero_copy_only=False).astype(np.float64, copy=True)
                vals[is_n] = np.nan
                mat[:, j] = vals

        # Нормализуем -0.0 -> +0.0 векторно
        zero_pos = (~null_mask) & (~np.isnan(mat)) & (mat == 0.0)
        mat[zero_pos] = 0.0
        return mat, null_mask


def resolve_city_csv_route(file_path: Path) -> str | None:
    """Определяет внутренний контрактный путь по имени файла в папке города."""
    if file_path.suffix.lower() != ".csv":
        return None
    stem = _normalize_stem(file_path.name)
    return CITY_TABLE_STEM_MAP.get(stem)


def is_aquabit_city_directory(path: Path) -> bool:
    """Возвращает True, если директория содержит CSV-таблицы города AquaBit."""
    if not path.is_dir():
        return False
    matched = 0
    for child in path.iterdir():
        if child.is_file() and resolve_city_csv_route(child) is not None:
            matched += 1
    return matched >= 2


def discover_city_directories(root_path: Path) -> list[Path]:
    """Находит одну папку города либо все подпапки городов внутри каталога data/."""
    p = Path(root_path)
    if not p.exists() or not p.is_dir():
        return []
    if is_aquabit_city_directory(p):
        return [p]
    found: list[Path] = []
    for sub in sorted(p.iterdir(), key=lambda x: unicodedata.normalize("NFC", x.name).lower()):
        if sub.is_dir() and not sub.name.startswith(".") and is_aquabit_city_directory(sub):
            found.append(sub)
    return found


def _sha256_and_probe_file(file_path: Path) -> tuple[str, int, bytes, bool]:
    """Стримингово считает SHA-256 файла и читает первые 256 КБ + проверяет UTF-8."""
    h = hashlib.sha256()
    size = 0
    head_chunks: list[bytes] = []
    head_collected = 0
    utf8_ok = True
    inc_decoder = _make_utf8_incremental_Validator()

    with file_path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
            if head_collected < 262144:
                take = chunk[: 262144 - head_collected]
                head_chunks.append(take)
                head_collected += len(take)
            if utf8_ok:
                try:
                    inc_decoder.decode(chunk, final=False)
                except UnicodeDecodeError:
                    utf8_ok = False
        if utf8_ok:
            try:
                inc_decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                utf8_ok = False

    return h.hexdigest(), size, b"".join(head_chunks), utf8_ok


def _make_utf8_incremental_Validator():
    import codecs

    return codecs.getincrementaldecoder("utf-8")("strict")


def _infer_step_seconds_from_count(n_steps: int) -> int:
    if n_steps <= 0:
        return 3600
    if n_steps == 1440:
        return 60
    if n_steps == 24:
        return 3600
    if n_steps == 48:
        return 1800
    if n_steps == 96:
        return 900
    if n_steps == 288:
        return 300
    if 86400 % n_steps == 0:
        return 86400 // n_steps
    return max(1, round(86400 / n_steps))


def _pinpoint_wide_csv_error(
    file_path: Path,
    canonical_path: str,
    encoding: str,
    delimiter: str,
    expected_headers: list[str],
) -> tuple[list[dict[str, Any]], str | None]:
    """Локализует точную строку/колонку ошибки, если C++-парсер PyArrow отклонил широкий CSV."""
    ragged: list[dict[str, Any]] = []
    expected_w = len(expected_headers)
    try:
        with file_path.open("r", encoding=encoding, newline="") as f:
            reader = csv.reader(f, delimiter=delimiter)
            next(reader, None)  # пропускаем заголовок
            for row_num, row in enumerate(reader, start=2):
                if not row:
                    continue
                if len(row) != expected_w:
                    ragged.append(
                        {
                            "file": canonical_path,
                            "source_file": file_path.name,
                            "line_number": row_num,
                            "expected_columns": expected_w,
                            "actual_columns": len(row),
                        }
                    )
                    if len(ragged) >= 10:
                        break
                    continue
                for col_idx in range(1, expected_w):
                    cell = row[col_idx].strip()
                    if cell in NULL_TOKENS_LIST or cell in NAN_TOKENS_SET:
                        continue
                    if "," in cell:
                        return (
                            ragged,
                            f"LOCALE_DECIMAL_MISMATCH: запятая в числе '{row[col_idx]}' "
                            f"(строка {row_num}, колонка {expected_headers[col_idx]})",
                        )
                    try:
                        val = float(cell)
                        if np.isinf(val):
                            return (
                                ragged,
                                f"INVALID_NUMERIC_VALUE: бесконечность '{row[col_idx]}' "
                                f"(строка {row_num}, колонка {expected_headers[col_idx]})",
                            )
                    except ValueError:
                        return (
                            ragged,
                            f"INVALID_NUMERIC_VALUE: некорректное число '{row[col_idx]}' "
                            f"(строка {row_num}, колонка {expected_headers[col_idx]})",
                        )
    except Exception as exc:  # pragma: no cover
        return (ragged, f"Ошибка чтения CSV: {exc}")
    return (ragged, None)


def read_wide_timeseries_file(
    file_path: Path,
    canonical_path: str,
) -> IngestedCSVTable:
    """Быстрое чтение широкой матрицы ID,R0..R{T-1} через PyArrow C++ CSV Engine."""
    t0 = time.perf_counter()
    sha, size, head_bytes, utf8_stream_ok = _sha256_and_probe_file(file_path)
    has_bom = head_bytes.startswith(b"\xef\xbb\xbf")

    utf8_err: str | None = None
    detected_encoding: str | None = None

    if utf8_stream_ok:
        detected_encoding = "utf-8-sig" if has_bom else "utf-8"
    else:
        _, _, _, utf8_err = _detect_encoding_raw(head_bytes)
        try:
            head_bytes.decode("cp1251")
            detected_encoding = "cp1251"
        except UnicodeDecodeError:
            return IngestedCSVTable(
                relative_path=canonical_path,
                sha256=sha,
                size_bytes=size,
                detected_encoding=None,
                has_bom=has_bom,
                utf8_decode_error=utf8_err or "Неизвестная бинарная кодировка",
                detected_delimiter=None,
                raw_headers=[],
                parse_error="Файл не удалось декодировать как текст",
                dataframe=None,
                source_label=file_path.name,
            )

    head_text = head_bytes.decode(detected_encoding, errors="replace")
    if not head_text.strip():
        return IngestedCSVTable(
            relative_path=canonical_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=detected_encoding,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter=",",
            raw_headers=[],
            parse_error="Пустой CSV-файл",
            dataframe=None,
            source_label=file_path.name,
        )

    # Извлекаем полную первую строку заголовка напрямую из файла (у R0..R1439 заголовок ~8.5 КБ)
    with file_path.open("r", encoding=detected_encoding, newline="") as fh:
        first_non_empty = ""
        for line in fh:
            if line.strip():
                first_non_empty = line
                break

    delimiter = _detect_csv_delimiter(first_non_empty)
    raw_headers = next(csv.reader([first_non_empty], delimiter=delimiter))

    if len(raw_headers) < 2:
        return IngestedCSVTable(
            relative_path=canonical_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=detected_encoding,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter=delimiter,
            raw_headers=raw_headers,
            parse_error="В широкой матрице отсутствуют колонки шагов R0..R{T-1}",
            dataframe=None,
            source_label=file_path.name,
        )

    id_col_raw = raw_headers[0]
    step_cols: list[str] = []
    step_indices: list[int] = []
    non_step_cols: list[str] = []

    for h in raw_headers[1:]:
        m = WIDE_STEP_HEADER_RE.match(h.strip())
        if m is not None:
            step_cols.append(h)
            step_indices.append(int(m.group(1)))
        else:
            non_step_cols.append(h)

    if non_step_cols or not step_cols:
        # Если таблица не формата ID,R0..R{T-1} — читаем стандартным строковым парсером
        tbl = _read_raw_csv_bytes(canonical_path, file_path.read_bytes())
        tbl.source_label = file_path.name
        return tbl

    # Проверяем дублирующиеся заголовки до вызова PyArrow
    dup_h = [h for h, cnt in Counter(h.strip() for h in raw_headers).items() if cnt > 1 or h == ""]
    if dup_h:
        return IngestedCSVTable(
            relative_path=canonical_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=detected_encoding,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter=delimiter,
            raw_headers=raw_headers,
            dataframe=pd.DataFrame(columns=raw_headers),
            source_label=file_path.name,
        )

    col_types: dict[str, pa.DataType] = {id_col_raw: pa.string()}
    for sc in step_cols:
        col_types[sc] = pa.float64()

    pa_encoding = "utf8" if detected_encoding in {"utf-8", "utf-8-sig"} else detected_encoding
    read_opts = pacsv.ReadOptions(encoding=pa_encoding, block_size=16 * 1024 * 1024)
    parse_opts = pacsv.ParseOptions(delimiter=delimiter)
    convert_opts = pacsv.ConvertOptions(
        column_types=col_types,
        null_values=NULL_TOKENS_LIST,
        strings_can_be_null=True,
        quoted_strings_can_be_null=False,
    )

    try:
        if has_bom:
            # Сдвигаем поток на 3 байта UTF-8 BOM, чтобы имя первой колонки было ровно 'ID'
            with file_path.open("rb") as bf:
                bf.seek(3)
                pa_table = pacsv.read_csv(
                    bf,
                    read_options=read_opts,
                    parse_options=parse_opts,
                    convert_options=convert_opts,
                )
        else:
            pa_table = pacsv.read_csv(
                file_path,
                read_options=read_opts,
                parse_options=parse_opts,
                convert_options=convert_opts,
            )
    except (pa.ArrowInvalid, pa.ArrowException) as exc:
        ragged, parse_err = _pinpoint_wide_csv_error(
            file_path=file_path,
            canonical_path=canonical_path,
            encoding=detected_encoding,
            delimiter=delimiter,
            expected_headers=raw_headers,
        )
        return IngestedCSVTable(
            relative_path=canonical_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=detected_encoding,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter=delimiter,
            raw_headers=raw_headers,
            ragged_rows=ragged,
            parse_error=parse_err or f"Ошибка парсинга широкой матрицы PyArrow: {exc}",
            dataframe=None,
            source_label=file_path.name,
        )

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    contract = get_contract_for_path(canonical_path)
    metric_name = (
        contract.wide_metric_canonical
        if contract and contract.wide_metric_canonical
        else "value"
    )
    target_etype = (
        contract.wide_target_entity_type
        if contract and contract.wide_target_entity_type
        else "node"
    )

    wide_obj = WideTimeseriesMatrix(
        source_filename=file_path.name,
        canonical_path=canonical_path,
        canonical_metric=metric_name,
        target_entity_type=target_etype,
        id_column_raw=id_col_raw,
        step_columns=step_cols,
        step_indices=step_indices,
        step_seconds=_infer_step_seconds_from_count(len(step_cols)),
        arrow_table=pa_table,
        parse_time_ms=elapsed_ms,
    )

    # Лёгкий DataFrame только со строковой колонкой ID для мгновенных проверок Этапа 2
    id_strings = ["" if v is None else v for v in wide_obj.id_list()]
    light_df = pd.DataFrame({id_col_raw: id_strings}, dtype="object")

    return IngestedCSVTable(
        relative_path=canonical_path,
        sha256=sha,
        size_bytes=size,
        detected_encoding=detected_encoding,
        has_bom=has_bom,
        utf8_decode_error=utf8_err,
        detected_delimiter=delimiter,
        raw_headers=raw_headers,
        dataframe=light_df,
        wide_matrix=wide_obj,
        source_label=file_path.name,
    )


def _read_consumption_schedule_file(file_path: Path) -> IngestedCSVTable:
    """Читает График потребления.csv (ID,Данные), поддерживая все 3 варианта сериализации:
    1) многострочный ряд: несколько строк с одинаковым ID (t109,0.899 / t109,0.670 ...);
    2) строка с дополнительными запятыми: t109,0.899,0.670,... при заголовке ID,Данные;
    3) значения через пробел или точку с запятой внутри ячейки Данные: t109,"0.899 0.670 ...".
    """
    raw_bytes = file_path.read_bytes()
    sha = hashlib.sha256(raw_bytes).hexdigest()
    size = len(raw_bytes)
    encoding, has_bom, decoded_text, utf8_err = _detect_encoding_raw(raw_bytes)

    if decoded_text is None or not decoded_text.strip():
        tbl = _read_raw_csv_bytes("irregularity_curves.csv", raw_bytes)
        tbl.source_label = file_path.name
        return tbl

    delimiter = _detect_csv_delimiter(decoded_text)
    rows = list(csv.reader(io.StringIO(decoded_text), delimiter=delimiter))
    if not rows:
        tbl = _read_raw_csv_bytes("irregularity_curves.csv", raw_bytes)
        tbl.source_label = file_path.name
        return tbl

    raw_headers = [h.strip() for h in rows[0]]
    # Если уже есть явная колонка шага или времени — используем стандартный парсер
    lowered = {h.lower() for h in raw_headers}
    if any(k in lowered for k in ("step_index", "step", "шаг", "час", "time_iso8601", "время")):
        tbl = _read_raw_csv_bytes("irregularity_curves.csv", raw_bytes)
        tbl.source_label = file_path.name
        return tbl

    if len(raw_headers) != 2:
        tbl = _read_raw_csv_bytes("irregularity_curves.csv", raw_bytes)
        tbl.source_label = file_path.name
        return tbl

    id_h, val_h = raw_headers[0], raw_headers[1]
    step_counters: Counter[str] = Counter()
    normalized_rows: list[list[str]] = []
    ragged_rows: list[dict[str, Any]] = []

    for line_idx, row in enumerate(rows[1:], start=2):
        if not row or all(c.strip() == "" for c in row):
            continue
        if len(row) < 2:
            ragged_rows.append(
                {
                    "file": "irregularity_curves.csv",
                    "source_file": file_path.name,
                    "line_number": line_idx,
                    "expected_columns": 2,
                    "actual_columns": len(row),
                }
            )
            continue

        cid = row[0]
        raw_tail = row[1:]
        tokens: list[str] = []
        if len(raw_tail) > 1:
            # Формат t109,0.899,0.670,... (несколько колонок под заголовком Данные)
            tokens = [t.strip() for t in raw_tail if t.strip() != ""]
        else:
            cell = raw_tail[0].strip()
            if (" " in cell or ";" in cell) and not cell.startswith("{"):
                parts = [p.strip() for p in re.split(r"[;\s]+", cell) if p.strip() != ""]
                tokens = parts if parts else [cell]
            else:
                tokens = [raw_tail[0]]

        for tok in tokens:
            idx_val = step_counters[cid]
            step_counters[cid] += 1
            normalized_rows.append([cid, str(idx_val), tok])

    out_headers = [id_h, "step_index", val_h]
    df = pd.DataFrame(normalized_rows, columns=out_headers, dtype="object")
    return IngestedCSVTable(
        relative_path="irregularity_curves.csv",
        sha256=sha,
        size_bytes=size,
        detected_encoding=encoding,
        has_bom=has_bom,
        utf8_decode_error=utf8_err,
        detected_delimiter=delimiter,
        raw_headers=out_headers,
        ragged_rows=ragged_rows,
        dataframe=df if not ragged_rows else None,
        source_label=file_path.name,
    )


def _read_qh_curve_file(file_path: Path) -> IngestedCSVTable:
    """Читает Кривая QH.csv (ID,X,Y), добавляя порядковый индекс точки step_index внутри каждой кривой."""
    tbl = _read_raw_csv_bytes("pump_curves.csv", file_path.read_bytes())
    tbl.source_label = file_path.name
    if tbl.dataframe is None or tbl.dataframe.empty:
        return tbl

    headers_lower = {h.strip().lower() for h in tbl.raw_headers}
    if "step_index" not in headers_lower and len(tbl.raw_headers) >= 3:
        id_col = tbl.raw_headers[0]
        counters: Counter[str] = Counter()
        steps: list[str] = []
        for cid in tbl.dataframe[id_col].tolist():
            s_idx = counters[str(cid)]
            counters[str(cid)] += 1
            steps.append(str(s_idx))
        df_copy = tbl.dataframe.copy()
        df_copy["step_index"] = pd.Series(steps, index=df_copy.index, dtype="object")
        tbl.dataframe = df_copy
        tbl.raw_headers = [*tbl.raw_headers, "step_index"]
    return tbl


def _has_nonzero_wide_head(table: IngestedCSVTable | None) -> bool:
    if table is None or table.wide_matrix is None:
        return False
    w: WideTimeseriesMatrix = table.wide_matrix
    if w.num_rows == 0 or w.n_steps == 0:
        return False
    # Проверяем первые и средние колонки без полного копирования, затем при необходимости все
    probe_cols = [w.step_columns[0], w.step_columns[w.n_steps // 2], w.step_columns[-1]]
    for c in probe_cols:
        arr = w.arrow_table.column(c).to_numpy(zero_copy_only=False)
        valid = arr[~np.isnan(arr)]
        if valid.size > 0 and np.any(np.abs(valid) > 0.0):
            return True
    mat, null_mask = w.to_numpy_with_null_mask()
    valid_all = (~null_mask) & (~np.isnan(mat)) & (np.abs(mat) > 0.0)
    return bool(np.any(valid_all))


def _synthesize_city_manifest(
    city_dir: Path,
    tables: dict[str, IngestedCSVTable],
) -> tuple[ManifestSchema, dict[str, Any]]:
    """Формирует метаданные паспорта модели для папки города при отсутствии manifest.json."""
    city_name = unicodedata.normalize("NFC", city_dir.name)
    slug = re.sub(r"[^\w\-]+", "_", city_name, flags=re.UNICODE).strip("_") or "city"

    n_steps = 1
    step_seconds = 3600
    for tbl in tables.values():
        if tbl.wide_matrix is not None:
            w: WideTimeseriesMatrix = tbl.wide_matrix
            if w.n_steps > n_steps:
                n_steps = w.n_steps
                step_seconds = w.step_seconds

    has_results = _has_nonzero_wide_head(tables.get("wide/node_head.csv"))

    def _rows(p: str) -> int:
        t = tables.get(p)
        if t is None:
            return 0
        if t.wide_matrix is not None:
            return int(t.wide_matrix.num_rows)
        return int(len(t.dataframe)) if t.dataframe is not None else 0

    raw_dict: dict[str, Any] = {
        "schema_version": "1.0-city-folder",
        "export_id": f"city-folder-{slug}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "aquabit_version": "city_folder_csv_13",
        "model": {
            "id": f"CITY-{slug}",
            "name": city_name,
            "revision": "folder-v1",
        },
        "scenario": {
            "id": "SCEN-24H",
            "name": f"Суточный расчёт ({n_steps} шагов)",
            "revision": "r1",
        },
        "calculation": {
            "id": f"CALC-{slug}",
            "status": "performed" if has_results else "not_performed",
            "method_headloss": "unknown_city_folder",
            "solver": "aquabit",
            "converged": True if has_results else None,
        },
        "period": {
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-01-02T00:00:00+00:00" if n_steps > 1 else "2026-01-01T00:00:00+00:00",
            "step_seconds": step_seconds,
            "n_steps": n_steps,
            "timezone": "UTC",
        },
        "units": {
            "head": "m",
            "flow": "m3_h",
            "pressure": "m",
            "velocity": "m_s",
            "length": "m",
            "diameter": "mm",
        },
        "counts": {
            "nodes": _rows("nodes.csv"),
            "pipes": _rows("pipes.csv"),
            "pumps": _rows("pumps.csv"),
            "reservoirs": _rows("reservoirs.csv"),
            "valves": _rows("valves.csv"),
            "sources": _rows("sources.csv"),
        },
    }
    return ManifestSchema.model_validate(raw_dict), raw_dict


def ingest_city_directory(
    city_dir: str | Path,
    run_id: str | None = None,
) -> IngestionBundle:
    """Читает папку города AquaBit (data/<город>/*.csv) в канонический IngestionBundle."""
    dir_path = Path(city_dir)
    rid = run_id or generate_run_id()

    if not dir_path.exists() or not dir_path.is_dir():
        return IngestionBundle(
            run_id=rid,
            archive_path=dir_path,
            archive_sha256=None,
            archive_size_bytes=None,
            manifest=None,
            raw_manifest_dict=None,
            tables={},
            raw_snapshot=[],
            ingestion_issues=[
                ValidationCheckItem(
                    code=CheckCode.MISSING_FILE,
                    severity="fatal",
                    count=1,
                    message=f"Директория города не найдена: {dir_path}",
                    examples=[{"path": str(dir_path)}],
                )
            ],
        )

    tables: dict[str, IngestedCSVTable] = {}
    snapshots: list[RawFileSnapshot] = []
    issues: list[ValidationCheckItem] = []
    total_bytes = 0
    folder_hasher = hashlib.sha256()

    manifest_obj: ManifestSchema | None = None
    raw_manifest_dict: dict[str, Any] | None = None
    pruned_transit_nodes: set[str] = set()
    pruned_standby_pumps: set[str] = set()

    pruned_manifest_path = dir_path / "pruned_zero_manifest.json"
    if pruned_manifest_path.is_file():
        try:
            pm_raw = json.loads(pruned_manifest_path.read_text(encoding="utf-8"))
            pruned_transit_nodes = {str(x) for x in pm_raw.get("pruned_transit_node_ids", [])}
            pruned_standby_pumps = {str(x) for x in pm_raw.get("pruned_standby_pump_ids", [])}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass

    entries = sorted(
        [p for p in dir_path.iterdir() if p.is_file() and p.name not in IGNORED_ARCHIVE_ENTRIES],
        key=lambda p: unicodedata.normalize("NFC", p.name).lower(),
    )

    for entry in entries:
        if entry.name.lower() == "manifest.json":
            m_bytes = entry.read_bytes()
            m_sha = hashlib.sha256(m_bytes).hexdigest()
            total_bytes += len(m_bytes)
            folder_hasher.update(m_sha.encode("ascii"))
            snapshots.append(
                RawFileSnapshot(
                    relative_path="manifest.json",
                    sha256=m_sha,
                    size_bytes=len(m_bytes),
                    is_csv=False,
                )
            )
            try:
                raw_manifest_dict = json.loads(m_bytes.decode("utf-8-sig"))
                manifest_obj = ManifestSchema.model_validate(raw_manifest_dict)
            except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
                issues.append(
                    ValidationCheckItem(
                        code=CheckCode.MANIFEST_INVALID,
                        severity="fatal",
                        count=1,
                        message=f"Некорректный manifest.json в папке '{dir_path.name}': {exc}",
                        examples=[{"file": entry.name, "detail": str(exc)}],
                    )
                )
            continue

        canonical_route = resolve_city_csv_route(entry)
        if canonical_route is None:
            continue

        contract = get_contract_for_path(canonical_route)
        if contract is not None and contract.is_wide_timeseries:
            tbl = read_wide_timeseries_file(entry, canonical_route)
        elif canonical_route == "irregularity_curves.csv":
            tbl = _read_consumption_schedule_file(entry)
        elif canonical_route == "pump_curves.csv":
            tbl = _read_qh_curve_file(entry)
        else:
            tbl = _read_raw_csv_bytes(canonical_route, entry.read_bytes())
            tbl.source_label = entry.name

        tables[canonical_route] = tbl
        total_bytes += tbl.size_bytes
        folder_hasher.update(f"{canonical_route}:{tbl.sha256}".encode("utf-8"))
        row_cnt = (
            tbl.wide_matrix.num_rows
            if tbl.wide_matrix is not None
            else (len(tbl.dataframe) if tbl.dataframe is not None else None)
        )
        hdr_preview = (
            [*tbl.raw_headers[:4], "...", tbl.raw_headers[-1]]
            if len(tbl.raw_headers) > 8
            else tbl.raw_headers
        )
        snapshots.append(
            RawFileSnapshot(
                relative_path=f"{canonical_route} ({entry.name})",
                sha256=tbl.sha256,
                size_bytes=tbl.size_bytes,
                is_csv=True,
                detected_encoding=tbl.detected_encoding,
                has_bom=tbl.has_bom,
                detected_delimiter=tbl.detected_delimiter,
                rows=row_cnt,
                columns=len(tbl.raw_headers),
                raw_headers=hdr_preview,
                read_error=tbl.parse_error,
            )
        )

    missing_mandatory = [req for req in MANDATORY_CITY_TABLES if req not in tables]
    if missing_mandatory:
        issues.append(
            ValidationCheckItem(
                code=CheckCode.MISSING_FILE,
                severity="fatal",
                count=len(missing_mandatory),
                message=(
                    f"В папке города '{dir_path.name}' отсутствуют обязательные таблицы сети: "
                    f"{', '.join(missing_mandatory)}"
                ),
                developer_hint=(
                    "В папке города должны присутствовать как минимум Узел.csv (nodes.csv), "
                    "Труба.csv (pipes.csv) и Источники.csv (sources.csv)."
                ),
                examples=[{"missing_table": m} for m in missing_mandatory],
            )
        )

    if manifest_obj is None and not any(i.code == CheckCode.MANIFEST_INVALID for i in issues):
        manifest_obj, raw_manifest_dict = _synthesize_city_manifest(dir_path, tables)

    return IngestionBundle(
        run_id=rid,
        archive_path=dir_path,
        archive_sha256=folder_hasher.hexdigest(),
        archive_size_bytes=total_bytes,
        manifest=manifest_obj,
        raw_manifest_dict=raw_manifest_dict,
        tables=tables,
        raw_snapshot=snapshots,
        ingestion_issues=issues,
        pruned_transit_node_ids=pruned_transit_nodes,
        pruned_standby_pump_ids=pruned_standby_pumps,
    )
