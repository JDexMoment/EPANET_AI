"""Оркестратор подэтапов Этапа 3 — Preprocessing (§4, п. 3.1–3.10 + векторизованные широкие матрицы ADR-0007)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from aquabit_ai.config.csv_contracts import AliasRegistry
from aquabit_ai.ingest.archive import IngestionBundle
from aquabit_ai.preprocess.log import PreprocessingLogger
from aquabit_ai.preprocess.s3_1_encoding_delimiter import normalize_encoding_and_delimiter
from aquabit_ai.preprocess.s3_2_column_typing import apply_column_typing
from aquabit_ai.preprocess.s3_3_field_canonicalization import canonicalize_field_names
from aquabit_ai.preprocess.s3_4_unit_canonicalization import canonicalize_units
from aquabit_ai.preprocess.s3_5_time_canonicalization import canonicalize_timestamps
from aquabit_ai.preprocess.s3_6_entity_registry import EntityRegistryEntry, build_entity_registry
from aquabit_ai.preprocess.s3_7_cross_references import verify_and_normalize_cross_references
from aquabit_ai.preprocess.s3_8_missing_values import ColumnMissingStats, audit_missing_values
from aquabit_ai.preprocess.s3_9_quality_flags import (
    compute_quality_flags_and_report,
    write_normalized_parquet_and_reports,
)
from aquabit_ai.preprocess.wide_timeseries import (
    WidePreprocessArtifact,
    build_wide_matrix_artifacts,
    write_wide_parquet_artifacts,
)


@dataclass
class PreprocessingOutcome:
    """Результат выполнения Этапа 3 (Preprocessing)."""

    tables: dict[str, pd.DataFrame]
    quality_tables: dict[str, pa.Table]
    entity_registry: dict[str, EntityRegistryEntry]
    missing_stats: dict[str, dict[str, ColumnMissingStats]]
    converted_fields: set[tuple[str, str]]
    table_gap_flags: dict[str, list[bool]]
    quality_report: dict[str, Any]
    logger: PreprocessingLogger
    artifact_paths: dict[str, Path]
    wide_artifacts: dict[str, WidePreprocessArtifact] = dc_field(default_factory=dict)


def run_preprocessing(
    bundle: IngestionBundle,
    *,
    output_dir: Path | None = None,
    aliases: AliasRegistry | None = None,
    legacy_compat: bool = False,
    allow_broken_topology: bool = False,
    thresholds_config: dict[str, Any] | None = None,
    historical_baseline: dict[tuple[str, str], dict[str, float]] | None = None,
) -> PreprocessingOutcome:
    """Последовательно выполняет подэтапы 3.1 → 3.9 (+ 3.10 для широких матриц) над IngestionBundle."""
    registry = aliases or AliasRegistry.from_yaml()
    logger = PreprocessingLogger()

    # 3.1 Кодировка и разделитель
    s1_tables = normalize_encoding_and_delimiter(bundle, logger)

    # 3.2 Строгая типизация колонок ("" -> null, "0" -> 0.0, "NaN" -> IEEE NaN)
    s2_tables = apply_column_typing(s1_tables, registry, logger)

    # 3.3 Канонизация имён полей по field_aliases.yaml
    s3_tables, pending_unit_rules = canonicalize_field_names(
        s2_tables,
        registry,
        logger,
        legacy_compat=legacy_compat,
    )

    # 3.4 Канонизация единиц к manifest.units
    manifest_units = bundle.manifest.units if bundle.manifest is not None else None
    s4_tables, converted_fields = canonicalize_units(
        s3_tables,
        pending_unit_rules,
        manifest_units,
        logger,
    )

    # 3.5 Канонизация времени и фиксация дыр как null без интерполяции
    period = bundle.manifest.period if bundle.manifest is not None else None
    s5_tables, table_gap_flags = canonicalize_timestamps(s4_tables, period, logger)

    # 3.6 Построение единого реестра сущностей (ID registry)
    entity_registry = build_entity_registry(s5_tables, logger)

    # 3.7 Контроль и нормализация кросс-файловых связей (включая ID широких матриц)
    s7_tables = verify_and_normalize_cross_references(
        s5_tables,
        entity_registry,
        logger,
        legacy_compat=legacy_compat,
        allow_broken_topology=allow_broken_topology,
        pruned_transit_node_ids=bundle.pruned_transit_node_ids,
    )

    # Отделяем лёгкие 1-колоночные заглушки wide/* перед записью стандартных таблиц:
    # сами wide/* матрицы обрабатываются векторизованно в PyArrow (п. 3.10)
    wide_keys = {k for k, t in bundle.tables.items() if t.wide_matrix is not None}
    regular_tables = {k: v for k, v in s7_tables.items() if k not in wide_keys}
    regular_gap_flags = {k: v for k, v in table_gap_flags.items() if k not in wide_keys}

    # 3.8 Строгий аудит пропусков (null vs 0.0 vs NaN) без импутации
    missing_stats = audit_missing_values(regular_tables, logger)

    # 3.9 Флаги качества
    quality_tables, quality_report = compute_quality_flags_and_report(
        regular_tables,
        converted_fields,
        regular_gap_flags,
        logger,
        thresholds_config=thresholds_config,
        historical_baseline=historical_baseline,
    )

    # 3.10 Векторизованная нормализация широких временны́х матриц R0..R{T-1}
    wide_artifacts = build_wide_matrix_artifacts(bundle, logger)
    for w_key, w_art in sorted(wide_artifacts.items()):
        quality_report[w_key] = {
            "source_file": w_art.source_filename,
            "rows": w_art.n_rows,
            "n_steps": w_art.n_steps,
            "step_seconds": w_art.step_seconds,
            "canonical_metric": w_art.canonical_metric,
            "null_cells": w_art.null_cells,
            "zero_cells": w_art.zero_cells,
            "nan_cells": w_art.nan_cells,
        }
        if w_art.null_cells > 0:
            reason = f"{w_art.null_cells} null cells in wide matrix {w_key}"
            if reason not in quality_report["overall"]["reasons"]:
                quality_report["overall"]["reasons"].append(reason)
                quality_report["overall"]["status"] = "warning"

    artifact_paths: dict[str, Path] = {}
    if output_dir is not None:
        reg_dict = {oid: entry.to_dict() for oid, entry in entity_registry.items()}
        artifact_paths = write_normalized_parquet_and_reports(
            tables=regular_tables,
            quality_tables=quality_tables,
            quality_report=quality_report,
            entity_registry_dict=reg_dict,
            logger=logger,
            output_dir=output_dir,
        )
        wide_written = write_wide_parquet_artifacts(wide_artifacts, output_dir)
        artifact_paths.update(wide_written)
        if wide_artifacts:
            # Перезаписываем лог и quality_report с учётом записей подэтапа 3.10
            q_report_path = output_dir / "quality_report.json"
            q_report_path.write_text(
                json.dumps(quality_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.write_jsonl(output_dir / "preprocessing_log.jsonl")

    return PreprocessingOutcome(
        tables=regular_tables,
        quality_tables=quality_tables,
        entity_registry=entity_registry,
        missing_stats=missing_stats,
        converted_fields=converted_fields,
        table_gap_flags=regular_gap_flags,
        quality_report=quality_report,
        logger=logger,
        artifact_paths=artifact_paths,
        wide_artifacts=wide_artifacts,
    )
