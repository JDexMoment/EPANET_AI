"""Этап 1 — Ingestion: распаковка ZIP-экспорта AquaBit и чтение сырых строковых таблиц (§4, Этап 1)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from aquabit_ai import __version__
from aquabit_ai.config.csv_contracts import ALWAYS_MANDATORY_FILES
from aquabit_ai.config.manifest import (
    ExecutionMode,
    ManifestOutSchema,
    ManifestSchema,
    RawFileSnapshot,
)
from aquabit_ai.config.validation_models import CheckCode, ValidationCheckItem


IGNORED_ARCHIVE_ENTRIES = {".DS_Store", "Thumbs.db"}


@dataclass
class IngestedCSVTable:
    """Сырая CSV-таблица после Этапа 1 (без автотипизации, без переименования колонок)."""

    relative_path: str
    sha256: str
    size_bytes: int
    detected_encoding: str | None
    has_bom: bool
    utf8_decode_error: str | None
    detected_delimiter: str | None
    raw_headers: list[str]
    ragged_rows: list[dict[str, Any]] = field(default_factory=list)
    parse_error: str | None = None
    dataframe: pd.DataFrame | None = None
    wide_matrix: Any | None = None
    source_label: str | None = None


@dataclass
class IngestionBundle:
    """Результат Этапа 1 (Ingestion), передаваемый на Этап 2 (Validation)."""

    run_id: str
    archive_path: Path
    archive_sha256: str | None
    archive_size_bytes: int | None
    manifest: ManifestSchema | None
    raw_manifest_dict: dict[str, Any] | None
    tables: dict[str, IngestedCSVTable]
    raw_snapshot: list[RawFileSnapshot]
    ingestion_issues: list[ValidationCheckItem] = field(default_factory=list)
    pruned_transit_node_ids: set[str] = field(default_factory=set)
    pruned_standby_pump_ids: set[str] = field(default_factory=set)

    @property
    def has_fatal_ingestion_error(self) -> bool:
        return any(item.severity == "fatal" for item in self.ingestion_issues)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_encoding_raw(raw_bytes: bytes) -> tuple[str | None, bool, str | None, str | None]:
    """Проверяет читаемость UTF-8 / UTF-8-BOM и резервную кодировку cp1251 без изменения данных.

    Возвращает: (detected_encoding, has_bom, decoded_text, utf8_error_detail).
    """
    has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
    try:
        if has_bom:
            text = raw_bytes.decode("utf-8-sig")
            return ("utf-8-sig", True, text, None)
        text = raw_bytes.decode("utf-8")
        return ("utf-8", False, text, None)
    except UnicodeDecodeError as exc:
        utf8_err = f"Позиция байта {exc.start}..{exc.end}: {exc.reason}"
        # Проверяем, читается ли как Windows-1251 (для диагностики и --legacy-compat на Этапе 3.1)
        try:
            cp1251_text = raw_bytes.decode("cp1251")
            return ("cp1251", False, cp1251_text, utf8_err)
        except UnicodeDecodeError:
            return (None, False, None, utf8_err)


def _detect_csv_delimiter(sample_text: str) -> str:
    """Определяет фактический разделитель по непустой строке заголовка."""
    for line in sample_text.splitlines():
        if line.strip():
            # Подсчитываем разделители вне кавычек
            counts = {",": 0, "\t": 0, ";": 0}
            in_quotes = False
            for ch in line:
                if ch == '"':
                    in_quotes = not in_quotes
                elif not in_quotes and ch in counts:
                    counts[ch] += 1
            if counts["\t"] > 0 and counts[","] == 0:
                return "\t"
            if counts[";"] > 0 and counts[","] == 0:
                return ";"
            return ","
    return ","


def _read_raw_csv_bytes(relative_path: str, raw_bytes: bytes) -> IngestedCSVTable:
    """Читает CSV строго как строковый DataFrame без автотипизации и без заполнения пропусков."""
    sha = _sha256_bytes(raw_bytes)
    size = len(raw_bytes)
    encoding, has_bom, decoded_text, utf8_err = _detect_encoding_raw(raw_bytes)

    if decoded_text is None:
        return IngestedCSVTable(
            relative_path=relative_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=None,
            has_bom=has_bom,
            utf8_decode_error=utf8_err or "Неизвестная бинарная кодировка",
            detected_delimiter=None,
            raw_headers=[],
            parse_error="Файл не удалось декодировать как текст",
            dataframe=None,
        )

    if not decoded_text.strip():
        return IngestedCSVTable(
            relative_path=relative_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=encoding,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter=",",
            raw_headers=[],
            parse_error="Пустой CSV-файл (отсутствует строка заголовков)",
            dataframe=None,
        )

    delimiter = _detect_csv_delimiter(decoded_text)

    # Проверяем геометрию строк через стандартный csv.reader до построения DataFrame
    reader = csv.reader(io.StringIO(decoded_text), delimiter=delimiter)
    try:
        all_rows = list(reader)
    except csv.Error as exc:
        return IngestedCSVTable(
            relative_path=relative_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=encoding,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter=delimiter,
            raw_headers=[],
            parse_error=f"Ошибка синтаксиса CSV: {exc}",
            dataframe=None,
        )

    if not all_rows:
        return IngestedCSVTable(
            relative_path=relative_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=encoding,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter=delimiter,
            raw_headers=[],
            parse_error="Отсутствуют строки в CSV",
            dataframe=None,
        )

    raw_headers = list(all_rows[0])
    expected_width = len(raw_headers)
    ragged_rows: list[dict[str, Any]] = []
    data_rows: list[list[str]] = []

    for line_idx, row in enumerate(all_rows[1:], start=2):
        # Полностью пустая завершающая строка после \n игнорируется
        if len(row) == 0:
            continue
        if len(row) != expected_width:
            ragged_rows.append(
                {
                    "file": relative_path,
                    "line_number": line_idx,
                    "expected_columns": expected_width,
                    "actual_columns": len(row),
                }
            )
            continue
        data_rows.append(row)

    if ragged_rows:
        return IngestedCSVTable(
            relative_path=relative_path,
            sha256=sha,
            size_bytes=size,
            detected_encoding=encoding,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter=delimiter,
            raw_headers=raw_headers,
            ragged_rows=ragged_rows,
            parse_error=f"Несовпадение числа колонок в {len(ragged_rows)} строках",
            dataframe=None,
        )

    # Формируем сырой строковый DataFrame через pandas.read_csv с полным запретом автотипизации
    # (ADR-0001: dtype=str, keep_default_na=False, na_filter=False).
    # Если в сыром файле есть дублирующиеся заголовки, mangle_dupe_cols в новых версиях pandas
    # переименовал бы их в col.1 — поэтому передаём очищенный поток через read_csv только при
    # уникальных заголовках, а при дублях заголовков фиксируем как есть из csv.reader.
    if len(set(raw_headers)) == len(raw_headers):
        df = pd.read_csv(
            io.StringIO(decoded_text),
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            index_col=False,
        )
    else:
        df = pd.DataFrame(data_rows, columns=raw_headers, dtype=object).astype(str)

    return IngestedCSVTable(
        relative_path=relative_path,
        sha256=sha,
        size_bytes=size,
        detected_encoding=encoding,
        has_bom=has_bom,
        utf8_decode_error=utf8_err,
        detected_delimiter=delimiter,
        raw_headers=raw_headers,
        ragged_rows=[],
        parse_error=None,
        dataframe=df,
    )


def _normalize_extracted_root(temp_root: Path) -> Path:
    """Если архив упакован с одной внешней папкой-обёрткой, возвращает эту папку как корень."""
    if (temp_root / "manifest.json").is_file():
        return temp_root
    visible_children = [
        p
        for p in temp_root.iterdir()
        if p.name not in IGNORED_ARCHIVE_ENTRIES and not p.name.startswith("__MACOSX")
    ]
    if len(visible_children) == 1 and visible_children[0].is_dir():
        candidate = visible_children[0]
        if (candidate / "manifest.json").exists() or (candidate / "nodes.csv").exists():
            return candidate
    return temp_root


def _check_safe_zip_members(zf: zipfile.ZipFile) -> tuple[list[str], list[str]]:
    """Проверяет члены ZIP на шифрование и path traversal (Zip Slip)."""
    encrypted: list[str] = []
    unsafe_paths: list[str] = []
    for info in zf.infolist():
        if info.flag_bits & 0x1:
            encrypted.append(info.filename)
        member_path = Path(info.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            unsafe_paths.append(info.filename)
    return encrypted, unsafe_paths


def generate_run_id(now: datetime | None = None) -> str:
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d-%H%M%S")
    return f"run-{ts}"


def ingest_zip_archive(
    zip_path: str | Path,
    run_id: str | None = None,
) -> IngestionBundle:
    """Выполняет Этап 1 (Ingestion) для ZIP-экспорта AquaBit.

    1. Проверяет читаемость, целостность CRC и отсутствие шифрования ZIP.
    2. Безопасно распаковывает во временную директорию.
    3. Проверяет обязательные файлы (§2).
    4. Валидирует manifest.json по Pydantic-схеме.
    5. Читает все CSV строго как сырые строки без автотипизации и заполнения пропусков.
    6. Собирает raw_snapshot для manifest_out.json.
    """
    archive_path = Path(zip_path)
    effective_run_id = run_id or generate_run_id()
    issues: list[ValidationCheckItem] = []

    if not archive_path.exists() or not archive_path.is_file():
        issues.append(
            ValidationCheckItem(
                code=CheckCode.INVALID_ZIP,
                severity="fatal",
                count=1,
                message=f"Файл архива не найден: '{archive_path}'",
                developer_hint="Проверьте путь к ZIP-экспорту AquaBit.",
                examples=[{"archive": str(archive_path)}],
            )
        )
        return IngestionBundle(
            run_id=effective_run_id,
            archive_path=archive_path,
            archive_sha256=None,
            archive_size_bytes=None,
            manifest=None,
            raw_manifest_dict=None,
            tables={},
            raw_snapshot=[],
            ingestion_issues=issues,
        )

    archive_size = archive_path.stat().st_size
    archive_sha = _sha256_file(archive_path)

    # 1. Проверка целостности и отсутствия шифрования ZIP
    try:
        zf_ctx = zipfile.ZipFile(archive_path, mode="r")
    except (zipfile.BadZipFile, OSError) as exc:
        issues.append(
            ValidationCheckItem(
                code=CheckCode.INVALID_ZIP,
                severity="fatal",
                count=1,
                message=f"Файл '{archive_path.name}' не является корректным ZIP-архивом: {exc}",
                developer_hint="Убедитесь, что экспорт AquaBit завершён без обрыва записи.",
                examples=[{"archive": archive_path.name, "error": str(exc)}],
            )
        )
        return IngestionBundle(
            run_id=effective_run_id,
            archive_path=archive_path,
            archive_sha256=archive_sha,
            archive_size_bytes=archive_size,
            manifest=None,
            raw_manifest_dict=None,
            tables={},
            raw_snapshot=[],
            ingestion_issues=issues,
        )

    with zf_ctx as zf:
        encrypted_members, unsafe_members = _check_safe_zip_members(zf)
        if unsafe_members:
            issues.append(
                ValidationCheckItem(
                    code=CheckCode.UNSAFE_ZIP_PATH,
                    severity="fatal",
                    count=len(unsafe_members),
                    message="Обнаружены небезопасные пути (path traversal) внутри ZIP-архива",
                    developer_hint="Все пути внутри export.zip обязаны быть относительными без '..'.",
                    examples=[{"member": m} for m in unsafe_members[:10]],
                )
            )
            return IngestionBundle(
                run_id=effective_run_id,
                archive_path=archive_path,
                archive_sha256=archive_sha,
                archive_size_bytes=archive_size,
                manifest=None,
                raw_manifest_dict=None,
                tables={},
                raw_snapshot=[],
                ingestion_issues=issues,
            )

        if encrypted_members:
            issues.append(
                ValidationCheckItem(
                    code=CheckCode.ENCRYPTED_ZIP,
                    severity="fatal",
                    count=len(encrypted_members),
                    message="ZIP-архив зашифрован паролем — автоматическая обработка невозможна",
                    developer_hint="Формируйте незашифрованный ZIP-архив из AquaBit.",
                    examples=[{"member": m} for m in encrypted_members[:10]],
                )
            )
            return IngestionBundle(
                run_id=effective_run_id,
                archive_path=archive_path,
                archive_sha256=archive_sha,
                archive_size_bytes=archive_size,
                manifest=None,
                raw_manifest_dict=None,
                tables={},
                raw_snapshot=[],
                ingestion_issues=issues,
            )

        try:
            corrupted_member = zf.testzip()
        except (zipfile.BadZipFile, RuntimeError, zlib_error_types()) as exc:
            corrupted_member = f"<ошибка распаковки потока: {exc}>"

        if corrupted_member is not None:
            issues.append(
                ValidationCheckItem(
                    code=CheckCode.CORRUPTED_ZIP,
                    severity="fatal",
                    count=1,
                    message=f"Повреждён файл внутри ZIP-архива (ошибка CRC): '{corrupted_member}'",
                    developer_hint="Пересоздайте ZIP-экспорт в AquaBit.",
                    examples=[{"corrupted_member": str(corrupted_member)}],
                )
            )
            return IngestionBundle(
                run_id=effective_run_id,
                archive_path=archive_path,
                archive_sha256=archive_sha,
                archive_size_bytes=archive_size,
                manifest=None,
                raw_manifest_dict=None,
                tables={},
                raw_snapshot=[],
                ingestion_issues=issues,
            )

        # 2. Распаковка во временную директорию
        with tempfile.TemporaryDirectory(prefix="aquabit_ingest_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            zf.extractall(tmp_root)
            export_root = _normalize_extracted_root(tmp_root)

            # Собираем все файлы экспорта
            extracted_files: dict[str, Path] = {}
            for p in sorted(export_root.rglob("*")):
                if not p.is_file():
                    continue
                if p.name in IGNORED_ARCHIVE_ENTRIES or "__MACOSX" in p.parts:
                    continue
                rel = p.relative_to(export_root).as_posix()
                extracted_files[rel] = p

            # 4. Чтение и валидация manifest.json (если присутствует)
            manifest_model: ManifestSchema | None = None
            raw_manifest_dict: dict[str, Any] | None = None
            raw_snapshots: list[RawFileSnapshot] = []
            tables: dict[str, IngestedCSVTable] = {}

            if "manifest.json" in extracted_files:
                m_bytes = extracted_files["manifest.json"].read_bytes()
                m_enc, m_bom, m_text, m_utf8_err = _detect_encoding_raw(m_bytes)
                m_read_err: str | None = None
                if m_utf8_err is not None:
                    m_read_err = f"ENCODING_ERROR: {m_utf8_err}"
                    issues.append(
                        ValidationCheckItem(
                            code=CheckCode.ENCODING_ERROR,
                            severity="fatal",
                            count=1,
                            message=f"manifest.json не в кодировке UTF-8: {m_utf8_err}",
                            developer_hint="Сохраняйте manifest.json в UTF-8.",
                            examples=[{"file": "manifest.json", "detail": m_utf8_err}],
                        )
                    )
                elif m_text is not None:
                    try:
                        raw_manifest_dict = json.loads(m_text)
                        manifest_model = ManifestSchema.model_validate(raw_manifest_dict)
                    except json.JSONDecodeError as exc:
                        m_read_err = f"Некорректный JSON: {exc}"
                        issues.append(
                            ValidationCheckItem(
                                code=CheckCode.MANIFEST_INVALID,
                                severity="fatal",
                                count=1,
                                message=f"manifest.json содержит синтаксическую ошибку JSON: {exc}",
                                developer_hint="Проверьте сериализацию manifest.json в AquaBit.",
                                examples=[{"file": "manifest.json", "error": str(exc)}],
                            )
                        )
                    except ValidationError as exc:
                        m_read_err = f"Нарушение схемы ManifestSchema ({exc.error_count()} ошибок)"
                        err_examples = [
                            {
                                "field": ".".join(str(loc) for loc in e["loc"]),
                                "message": e["msg"],
                                "type": e["type"],
                            }
                            for e in exc.errors()[:10]
                        ]
                        issues.append(
                            ValidationCheckItem(
                                code=CheckCode.MANIFEST_INVALID,
                                severity="fatal",
                                count=exc.error_count(),
                                message="manifest.json не соответствует схеме §2 (Pydantic ManifestSchema)",
                                developer_hint=(
                                    "Проверьте обязательные поля manifest.json, строковые ID "
                                    "и наличие таймзоны в ISO 8601 датах."
                                ),
                                examples=err_examples,
                            )
                        )

                raw_snapshots.append(
                    RawFileSnapshot(
                        relative_path="manifest.json",
                        sha256=_sha256_bytes(m_bytes),
                        size_bytes=len(m_bytes),
                        is_csv=False,
                        detected_encoding=m_enc,
                        has_bom=m_bom,
                        read_error=m_read_err,
                    )
                )

            # 3. Проверка обязательных и условно-обязательных файлов из §2
            missing_files: list[dict[str, str]] = []
            for req_file in ALWAYS_MANDATORY_FILES:
                if req_file not in extracted_files:
                    missing_files.append(
                        {"file": req_file, "reason": "Обязательный файл экспорта (§2)"}
                    )

            if manifest_model is not None:
                if manifest_model.counts.reservoirs > 0 and "reservoirs.csv" not in extracted_files:
                    missing_files.append(
                        {
                            "file": "reservoirs.csv",
                            "reason": f"manifest.counts.reservoirs={manifest_model.counts.reservoirs} > 0",
                        }
                    )
                if manifest_model.counts.pumps > 0:
                    if "pumps.csv" not in extracted_files:
                        missing_files.append(
                            {
                                "file": "pumps.csv",
                                "reason": f"manifest.counts.pumps={manifest_model.counts.pumps} > 0",
                            }
                        )
                    if "pump_curves.csv" not in extracted_files:
                        missing_files.append(
                            {
                                "file": "pump_curves.csv",
                                "reason": f"manifest.counts.pumps={manifest_model.counts.pumps} > 0",
                            }
                        )
                if manifest_model.counts.valves > 0 and "valves.csv" not in extracted_files:
                    missing_files.append(
                        {
                            "file": "valves.csv",
                            "reason": f"manifest.counts.valves={manifest_model.counts.valves} > 0",
                        }
                    )

            if missing_files:
                issues.append(
                    ValidationCheckItem(
                        code=CheckCode.MISSING_FILE,
                        severity="fatal",
                        count=len(missing_files),
                        message=(
                            "В архиве отсутствуют обязательные файлы спецификации §2: "
                            + ", ".join(m["file"] for m in missing_files)
                        ),
                        developer_hint="Включите все обязательные таблицы в ZIP-экспорт AquaBit.",
                        examples=missing_files,
                    )
                )

            # 5. Чтение всех CSV как сырых строковых таблиц + сбор raw_snapshot
            for rel_path, file_path in extracted_files.items():
                if rel_path == "manifest.json":
                    continue
                f_bytes = file_path.read_bytes()
                if rel_path.lower().endswith(".csv"):
                    csv_table = _read_raw_csv_bytes(rel_path, f_bytes)
                    tables[rel_path] = csv_table
                    raw_snapshots.append(
                        RawFileSnapshot(
                            relative_path=rel_path,
                            sha256=csv_table.sha256,
                            size_bytes=csv_table.size_bytes,
                            is_csv=True,
                            detected_encoding=csv_table.detected_encoding,
                            has_bom=csv_table.has_bom,
                            detected_delimiter=csv_table.detected_delimiter,
                            rows=int(len(csv_table.dataframe)) if csv_table.dataframe is not None else None,
                            columns=(
                                int(len(csv_table.raw_headers))
                                if csv_table.raw_headers
                                else None
                            ),
                            raw_headers=csv_table.raw_headers or None,
                            read_error=csv_table.parse_error or csv_table.utf8_decode_error,
                        )
                    )
                else:
                    raw_snapshots.append(
                        RawFileSnapshot(
                            relative_path=rel_path,
                            sha256=_sha256_bytes(f_bytes),
                            size_bytes=len(f_bytes),
                            is_csv=False,
                        )
                    )

    raw_snapshots.sort(key=lambda s: s.relative_path)

    return IngestionBundle(
        run_id=effective_run_id,
        archive_path=archive_path,
        archive_sha256=archive_sha,
        archive_size_bytes=archive_size,
        manifest=manifest_model,
        raw_manifest_dict=raw_manifest_dict,
        tables=tables,
        raw_snapshot=raw_snapshots,
        ingestion_issues=issues,
    )


def zlib_error_types() -> tuple[type[BaseException], ...]:
    import zlib

    return (zlib.error, EOFError)


def build_manifest_out(
    bundle: IngestionBundle,
    stage_completed: str = "stage1_ingest",
    requested_mode: ExecutionMode | None = None,
    effective_mode: ExecutionMode | None = None,
    mode_switched: bool = False,
    validation_status: str = "not_run",
) -> ManifestOutSchema:
    """Формирует объект ManifestOutSchema для записи в manifest_out.json."""
    return ManifestOutSchema(
        run_id=bundle.run_id,
        pipeline_version=__version__,
        processed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        source_archive=bundle.archive_path.name,
        source_archive_sha256=bundle.archive_sha256,
        source_archive_size_bytes=bundle.archive_size_bytes,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        mode_switched=mode_switched,
        stage_completed=stage_completed,
        validation_status=validation_status,  # type: ignore[arg-type]
        manifest=bundle.manifest,
        raw_snapshot=bundle.raw_snapshot,
    )


def write_manifest_out(manifest_out: ManifestOutSchema, output_dir: Path) -> Path:
    """Сериализует manifest_out.json в указанную директорию артефактов."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "manifest_out.json"
    target.write_text(
        json.dumps(manifest_out.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
