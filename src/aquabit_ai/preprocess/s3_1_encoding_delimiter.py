"""Подэтап 3.1 — Кодировка и разделитель (§4, п. 3.1)."""

from __future__ import annotations

import csv
import io
import pandas as pd

from aquabit_ai.ingest.archive import IngestedCSVTable, IngestionBundle, _detect_csv_delimiter
from aquabit_ai.preprocess.errors import PreprocessingFatalError
from aquabit_ai.preprocess.log import PreprocessingLogger


STAGE_NAME = "3.1_encoding_delimiter"


def decode_and_parse_raw_csv_bytes(
    file_name: str,
    raw_bytes: bytes,
    logger: PreprocessingLogger,
    allow_replacement_on_corrupt: bool = False,
) -> pd.DataFrame:
    """Определяет кодировку (UTF-8 / UTF-8-BOM / Windows-1251) и разделитель (',' / '\\t' / ';'),
    фиксируя все действия в preprocessing_log.jsonl (§4, п. 3.1).
    """
    has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
    detected_enc: str | None = None
    transcoded = False
    unreadable_chars = 0
    text: str | None = None

    try:
        if has_bom:
            text = raw_bytes.decode("utf-8-sig")
            detected_enc = "utf-8-sig"
        else:
            text = raw_bytes.decode("utf-8")
            detected_enc = "utf-8"
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode("cp1251")
            detected_enc = "cp1251"
            transcoded = True
        except UnicodeDecodeError as exc:
            if not allow_replacement_on_corrupt:
                raise PreprocessingFatalError(
                    "ENCODING_ERROR",
                    f"Файл '{file_name}' не читается ни в UTF-8, ни в Windows-1251: {exc}",
                    file=file_name,
                    examples=[{"start_byte": exc.start, "end_byte": exc.end, "reason": exc.reason}],
                ) from exc
            text = raw_bytes.decode("utf-8", errors="replace")
            detected_enc = "utf-8-replaced"
            transcoded = True
            unreadable_chars = text.count("\ufffd")

    assert text is not None
    delimiter = _detect_csv_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows_list = [r for r in reader if len(r) > 0]
    if not rows_list:
        raise PreprocessingFatalError(
            "SCHEMA_MISMATCH",
            f"Файл '{file_name}' пуст",
            file=file_name,
        )

    headers = rows_list[0]
    width = len(headers)
    data_rows: list[list[str]] = []
    for idx, row in enumerate(rows_list[1:], start=2):
        if len(row) != width:
            raise PreprocessingFatalError(
                "SCHEMA_MISMATCH",
                f"Несовпадение ширины строки {idx} в '{file_name}': ожидалось {width}, получено {len(row)}",
                file=file_name,
                examples=[{"line_number": idx, "expected": width, "actual": len(row)}],
            )
        data_rows.append(row)

    df = pd.DataFrame(data_rows, columns=headers, dtype=object).astype(str)

    severity = "warning" if (transcoded or delimiter != ",") else "info"
    logger.record(
        stage=STAGE_NAME,
        operation="detect_encoding_and_delimiter",
        file=file_name,
        before={"encoding": detected_enc, "delimiter": delimiter},
        after={"encoding": "utf-8", "delimiter": ","},
        affected_rows=len(df),
        severity=severity,
        details={
            "detected_encoding": detected_enc,
            "detected_delimiter": delimiter,
            "transcoded_to_utf8": transcoded,
            "unreadable_chars": unreadable_chars,
            "rows": int(len(df)),
            "columns": int(len(headers)),
        },
    )
    return df


def normalize_encoding_and_delimiter(
    bundle: IngestionBundle,
    logger: PreprocessingLogger,
) -> dict[str, pd.DataFrame]:
    """Подэтап 3.1 для всех таблиц из IngestionBundle."""
    result: dict[str, pd.DataFrame] = {}

    for rel_path, table in sorted(bundle.tables.items()):
        _validate_ingested_table(rel_path, table)
        assert table.dataframe is not None
        df = table.dataframe.copy()

        transcoded = table.detected_encoding not in {"utf-8", "utf-8-sig"}
        delim = table.detected_delimiter or ","
        severity = "warning" if (transcoded or delim != ",") else "info"

        logger.record(
            stage=STAGE_NAME,
            operation="detect_encoding_and_delimiter",
            file=rel_path,
            before={"encoding": table.detected_encoding, "delimiter": delim},
            after={"encoding": "utf-8", "delimiter": ","},
            affected_rows=len(df),
            severity=severity,
            details={
                "detected_encoding": table.detected_encoding,
                "detected_delimiter": delim,
                "transcoded_to_utf8": transcoded,
                "unreadable_chars": 0,
                "rows": int(len(df)),
                "columns": int(len(df.columns)),
            },
        )
        result[rel_path] = df

    return result


def _validate_ingested_table(rel_path: str, table: IngestedCSVTable) -> None:
    if table.detected_encoding is None:
        raise PreprocessingFatalError(
            "ENCODING_ERROR",
            f"Файл '{rel_path}' не удалось декодировать: {table.utf8_decode_error}",
            file=rel_path,
            examples=[{"detail": table.utf8_decode_error}],
        )
    if table.dataframe is None:
        raise PreprocessingFatalError(
            "SCHEMA_MISMATCH",
            f"Файл '{rel_path}' не содержит корректной таблицы: {table.parse_error}",
            file=rel_path,
            examples=table.ragged_rows[:10],
        )
