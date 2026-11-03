"""Этап 3 — Preprocessing: 9 детерминированных подэтапов нормализации таблиц AquaBit."""

from __future__ import annotations

from aquabit_ai.preprocess.errors import PreprocessingFatalError
from aquabit_ai.preprocess.log import PreprocessingLogEntry, PreprocessingLogger
from aquabit_ai.preprocess.pipeline import PreprocessingOutcome, run_preprocessing
from aquabit_ai.preprocess.s3_1_encoding_delimiter import (
    decode_and_parse_raw_csv_bytes,
    normalize_encoding_and_delimiter,
)
from aquabit_ai.preprocess.s3_2_column_typing import apply_column_typing
from aquabit_ai.preprocess.s3_3_field_canonicalization import canonicalize_field_names
from aquabit_ai.preprocess.s3_4_unit_canonicalization import canonicalize_units
from aquabit_ai.preprocess.s3_5_time_canonicalization import canonicalize_timestamps
from aquabit_ai.preprocess.s3_6_entity_registry import EntityRegistryEntry, build_entity_registry
from aquabit_ai.preprocess.s3_7_cross_references import verify_and_normalize_cross_references
from aquabit_ai.preprocess.s3_8_missing_values import (
    ColumnMissingStats,
    audit_missing_values,
    inspect_column_masks,
)
from aquabit_ai.preprocess.s3_9_quality_flags import (
    compute_quality_flags_and_report,
    load_quality_thresholds,
    write_normalized_parquet_and_reports,
)

SUBSTAGE_ORDER: tuple[str, ...] = (
    "3.1_encoding_delimiter",
    "3.2_column_typing",
    "3.3_field_canonicalization",
    "3.4_unit_canonicalization",
    "3.5_time_canonicalization",
    "3.6_entity_registry",
    "3.7_cross_references",
    "3.8_missing_values",
    "3.9_quality_flags",
)

__all__ = [
    "ColumnMissingStats",
    "EntityRegistryEntry",
    "PreprocessingFatalError",
    "PreprocessingLogEntry",
    "PreprocessingLogger",
    "PreprocessingOutcome",
    "SUBSTAGE_ORDER",
    "apply_column_typing",
    "audit_missing_values",
    "build_entity_registry",
    "canonicalize_field_names",
    "canonicalize_timestamps",
    "canonicalize_units",
    "compute_quality_flags_and_report",
    "decode_and_parse_raw_csv_bytes",
    "inspect_column_masks",
    "load_quality_thresholds",
    "normalize_encoding_and_delimiter",
    "run_preprocessing",
    "verify_and_normalize_cross_references",
    "write_normalized_parquet_and_reports",
]
