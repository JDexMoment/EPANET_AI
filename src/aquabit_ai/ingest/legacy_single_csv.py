"""Адаптер текущего однофайлового многосекционного экспорта AquaBit («анализ *.csv», ADR-0006)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from aquabit_ai.config.manifest import (
    CalculationMetadata,
    CountsMetadata,
    ManifestSchema,
    ModelMetadata,
    PeriodMetadata,
    ScenarioMetadata,
    UnitsMetadata,
)
from aquabit_ai.config.validation_models import CheckCode, ValidationCheckItem
from aquabit_ai.ingest.archive import (
    IngestedCSVTable,
    IngestionBundle,
    RawFileSnapshot,
    _detect_encoding_raw,
    generate_run_id,
)


SECTION_TO_VIRTUAL_FILE: dict[str, str] = {
    "Список источников воды": "sources.csv",
    "Список узлов сети": "nodes.csv",
    "Базовое потребление узлов": "demands.csv",
    "Список труб сети": "pipes.csv",
    "Список клапанов сети": "valves.csv",
    "Список насосов сети": "pumps.csv",
    "Паспортные данные насосов": "pump_curves.csv",
    "Список резервуаров": "reservoirs.csv",
    "Список резервуаров сети": "reservoirs.csv",
    "Суточная неравномерность": "irregularity_curves.csv",
}

HEADLOSS_METHOD_MAP: dict[str, str] = {
    "хазен-вильямса": "hazen_williams",
    "хазена-вильямса": "hazen_williams",
    "hazen-williams": "hazen_williams",
    "дарси-вейсбаха": "darcy_weisbach",
    "darcy-weisbach": "darcy_weisbach",
    "шези-маннинга": "chezy_manning",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_legacy_moment(
    raw_moment: str,
    timezone_name: str,
    fallback_date: str = "2026-10-30",
) -> tuple[str, bool]:
    """Преобразует 'Момент расчета' ('28.11.2022 18:43:00' или '9:25:00') в ISO 8601 с TZ.

    Возвращает (iso_str, used_fallback_date_or_tz).
    """
    tz = ZoneInfo(timezone_name)
    cleaned = raw_moment.strip()
    # Формат ДД.ММ.ГГГГ ЧЧ:ММ[:СС]
    m_full = re.match(
        r"^(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$", cleaned
    )
    if m_full:
        day, month, year, hh, mm, ss = m_full.groups()
        dt = datetime(
            int(year),
            int(month),
            int(day),
            int(hh),
            int(mm),
            int(ss or 0),
            tzinfo=tz,
        )
        return (dt.isoformat(), True)

    # Формат только времени ЧЧ:ММ[:СС]
    m_time = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", cleaned)
    if m_time:
        y, mo, d = (int(x) for x in fallback_date.split("-"))
        hh, mm, ss = m_time.groups()
        dt = datetime(y, mo, d, int(hh), int(mm), int(ss or 0), tzinfo=tz)
        return (dt.isoformat(), True)

    # Фолбэк
    y, mo, d = (int(x) for x in fallback_date.split("-"))
    return (datetime(y, mo, d, 0, 0, 0, tzinfo=tz).isoformat(), True)


def is_legacy_multisection_csv(path: Path) -> bool:
    """Определяет, является ли файл многосекционной выгрузкой анализа AquaBit."""
    if not path.is_file() or path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
        return False
    raw = path.read_bytes()[:4096]
    _, _, text, _ = _detect_encoding_raw(raw)
    if not text:
        return False
    first_lines = "\n".join(text.splitlines()[:10])
    return (
        "Модель потери напора:" in first_lines
        or "Список источников воды" in first_lines
        or "Список узлов сети" in first_lines
    )


def ingest_legacy_analysis_csv(
    csv_path: str | Path,
    run_id: str | None = None,
    timezone_name: str = "Asia/Tashkent",
    fallback_date: str = "2026-10-30",
) -> IngestionBundle:
    """Читает однофайловую многосекционную выгрузку AquaBit в стандартный IngestionBundle (ADR-0006).

    Все значения сохраняются строго как сырые строки без автотипизации и без заполнения пропусков.
    Исходная кодировка (cp1251) и разделитель (\\t) фиксируются честно для Этапов 2 и 3.1.
    """
    source_path = Path(csv_path)
    effective_run_id = run_id or generate_run_id()
    issues: list[ValidationCheckItem] = []

    if not source_path.is_file():
        issues.append(
            ValidationCheckItem(
                code=CheckCode.MISSING_FILE,
                severity="fatal",
                count=1,
                message=f"Входной CSV-файл не найден: '{source_path}'",
                examples=[{"file": str(source_path)}],
            )
        )
        return IngestionBundle(
            run_id=effective_run_id,
            archive_path=source_path,
            archive_sha256=None,
            archive_size_bytes=None,
            manifest=None,
            raw_manifest_dict=None,
            tables={},
            raw_snapshot=[],
            ingestion_issues=issues,
        )

    raw_bytes = source_path.read_bytes()
    file_sha = _sha256_bytes(raw_bytes)
    file_size = len(raw_bytes)
    detected_enc, has_bom, decoded_text, utf8_err = _detect_encoding_raw(raw_bytes)

    if decoded_text is None:
        issues.append(
            ValidationCheckItem(
                code=CheckCode.ENCODING_ERROR,
                severity="fatal",
                count=1,
                message=f"Не удалось декодировать файл '{source_path.name}': {utf8_err}",
                examples=[{"file": source_path.name, "detail": utf8_err}],
            )
        )
        return IngestionBundle(
            run_id=effective_run_id,
            archive_path=source_path,
            archive_sha256=file_sha,
            archive_size_bytes=file_size,
            manifest=None,
            raw_manifest_dict=None,
            tables={},
            raw_snapshot=[],
            ingestion_issues=issues,
        )

    lines = decoded_text.splitlines()
    meta_kv: dict[str, str] = {}
    raw_sections: dict[str, tuple[list[str], list[list[str]]]] = {}

    idx = 0
    total_lines = len(lines)
    while idx < total_lines:
        line = lines[idx]
        if not line.strip():
            idx += 1
            continue
        if idx < 5 and ":\t" in line:
            k, v = line.split(":\t", 1)
            meta_kv[k.strip()] = v.strip()
            idx += 1
            continue
        if "\t" not in line:
            sec_title = line.strip()
            if idx + 1 >= total_lines:
                break
            hdr_cells = lines[idx + 1].split("\t")
            j = idx + 2
            sec_rows: list[list[str]] = []
            while j < total_lines and lines[j].strip() != "":
                sec_rows.append(lines[j].split("\t"))
                j += 1
            raw_sections[sec_title] = (hdr_cells, sec_rows)
            idx = j
        else:
            idx += 1

    tables: dict[str, IngestedCSVTable] = {}
    snapshots: list[RawFileSnapshot] = []

    for sec_title, (hdr, rows) in raw_sections.items():
        vfile = SECTION_TO_VIRTUAL_FILE.get(sec_title)
        if vfile is None:
            continue

        # Если опциональная секция (например, клапаны в "модель сетей") содержит 0 строк — пропускаем пустую таблицу
        if len(rows) == 0 and vfile in {"valves.csv", "reservoirs.csv", "pumps.csv"}:
            continue

        if vfile == "irregularity_curves.csv":
            # Разворачиваем широкую строку ('104', '1', '1', ...) в длинный сырой табличный вид без интерполяции
            long_headers = ["Идентификатор", "Шаг", "Коэффициент"]
            long_rows: list[list[str]] = []
            for r in rows:
                if not r:
                    continue
                cid = r[0]
                multipliers = r[1:]
                if not multipliers:
                    long_rows.append([cid, "0", ""])
                else:
                    for step_idx, mult_str in enumerate(multipliers):
                        long_rows.append([cid, str(step_idx), mult_str])
            df = pd.DataFrame(long_rows, columns=long_headers, dtype=object).astype(str)
            sec_bytes = (
                "\t".join(long_headers) + "\n" + "\n".join("\t".join(r) for r in long_rows)
            ).encode(detected_enc or "utf-8", errors="replace")
            effective_headers = long_headers
            ragged: list[dict[str, Any]] = []
        else:
            expected_w = len(hdr)
            ragged = []
            clean_rows: list[list[str]] = []
            for r_i, r in enumerate(rows, start=2):
                if len(r) != expected_w:
                    ragged.append(
                        {
                            "file": vfile,
                            "section": sec_title,
                            "line_number": r_i,
                            "expected_columns": expected_w,
                            "actual_columns": len(r),
                        }
                    )
                else:
                    clean_rows.append(r)

            effective_headers = hdr
            df = (
                pd.DataFrame(clean_rows, columns=hdr, dtype=object).astype(str)
                if not ragged
                else None
            )
            sec_bytes = (
                "\t".join(hdr) + "\n" + "\n".join("\t".join(r) for r in rows)
            ).encode(detected_enc or "utf-8", errors="replace")

        sec_sha = _sha256_bytes(sec_bytes)
        tables[vfile] = IngestedCSVTable(
            relative_path=vfile,
            sha256=sec_sha,
            size_bytes=len(sec_bytes),
            detected_encoding=detected_enc,
            has_bom=has_bom,
            utf8_decode_error=utf8_err,
            detected_delimiter="\t",
            raw_headers=effective_headers,
            ragged_rows=ragged,
            parse_error=(
                f"Несовпадение числа колонок в секции '{sec_title}'" if ragged else None
            ),
            dataframe=df,
        )
        snapshots.append(
            RawFileSnapshot(
                relative_path=vfile,
                sha256=sec_sha,
                size_bytes=len(sec_bytes),
                is_csv=True,
                detected_encoding=detected_enc,
                has_bom=has_bom,
                detected_delimiter="\t",
                rows=int(len(df)) if df is not None else None,
                columns=len(effective_headers),
                raw_headers=effective_headers,
                read_error=utf8_err,
            )
        )

    # Проверяем обязательные секции (§2)
    missing_mandatory = [
        {"file": req, "reason": "Отсутствует соответствующая секция в выгрузке анализа AquaBit"}
        for req in ("nodes.csv", "pipes.csv", "sources.csv")
        if req not in tables
    ]
    if missing_mandatory:
        issues.append(
            ValidationCheckItem(
                code=CheckCode.MISSING_FILE,
                severity="fatal",
                count=len(missing_mandatory),
                message="В однофайловой выгрузке AquaBit отсутствуют обязательные секции сети",
                examples=missing_mandatory,
            )
        )

    # Синтезируем канонический ManifestSchema из шапки однофайлового экспорта
    raw_method = meta_kv.get("Модель потери напора", "").lower()
    method_headloss = HEADLOSS_METHOD_MAP.get(raw_method, raw_method or "unknown")
    raw_moment = meta_kv.get("Момент расчета", "00:00:00")
    iso_moment, _ = _parse_legacy_moment(raw_moment, timezone_name, fallback_date)

    # Определяем наличие ненулевых рассчитанных напоров
    has_calc_heads = False
    nodes_tbl = tables.get("nodes.csv")
    if nodes_tbl is not None and nodes_tbl.dataframe is not None:
        for col in nodes_tbl.dataframe.columns:
            if "Рассчитанный Напор" in col or col == "calculated_head_m":
                for val in nodes_tbl.dataframe[col].tolist():
                    s = val.strip()
                    if s:
                        try:
                            if abs(float(s)) > 0.0:
                                has_calc_heads = True
                                break
                        except ValueError:
                            pass

    stem_slug = re.sub(r"\s+", "_", source_path.stem.strip())
    manifest = ManifestSchema(
        schema_version="1.0-legacy-csv",
        export_id=f"legacy-{file_sha[:12]}",
        created_at=iso_moment,
        aquabit_version="legacy-single-csv",
        model=ModelMetadata(
            id=f"M-{stem_slug}",
            name=source_path.stem,
            revision="legacy",
        ),
        scenario=ScenarioMetadata(
            id=f"S-{raw_moment.replace(' ', '_').replace(':', '-')}",
            name=f"Срез {raw_moment}",
            revision="legacy",
        ),
        calculation=CalculationMetadata(
            id=f"CALC-{file_sha[:8]}",
            status="performed" if has_calc_heads else "not_performed",
            method_headloss=method_headloss,
            converged=True if has_calc_heads else None,
        ),
        period=PeriodMetadata(
            start=iso_moment,
            end=iso_moment,
            step_seconds=3600,
            n_steps=1,
            timezone=timezone_name,
        ),
        units=UnitsMetadata(
            head="m",
            flow="m3_h",
            pressure="bar",
            velocity="m_s",
            length="m",
            diameter="mm",
        ),
        counts=CountsMetadata(
            nodes=len(tables["nodes.csv"].dataframe) if "nodes.csv" in tables and tables["nodes.csv"].dataframe is not None else 0,
            pipes=len(tables["pipes.csv"].dataframe) if "pipes.csv" in tables and tables["pipes.csv"].dataframe is not None else 0,
            pumps=len(tables["pumps.csv"].dataframe) if "pumps.csv" in tables and tables["pumps.csv"].dataframe is not None else 0,
            reservoirs=len(tables["reservoirs.csv"].dataframe) if "reservoirs.csv" in tables and tables["reservoirs.csv"].dataframe is not None else 0,
            valves=len(tables["valves.csv"].dataframe) if "valves.csv" in tables and tables["valves.csv"].dataframe is not None else 0,
            sources=len(tables["sources.csv"].dataframe) if "sources.csv" in tables and tables["sources.csv"].dataframe is not None else 0,
        ),
        missing_data_summary={},
    )

    snapshots.sort(key=lambda s: s.relative_path)
    return IngestionBundle(
        run_id=effective_run_id,
        archive_path=source_path,
        archive_sha256=file_sha,
        archive_size_bytes=file_size,
        manifest=manifest,
        raw_manifest_dict=manifest.model_dump(mode="json"),
        tables=tables,
        raw_snapshot=snapshots,
        ingestion_issues=issues,
    )
