"""Пакет распаковки и чтения сырых данных AquaBit (Этап 1 — Ingestion: ZIP, папка города, legacy CSV)."""

from __future__ import annotations

from pathlib import Path

from aquabit_ai.ingest.archive import (
    IngestedCSVTable,
    IngestionBundle,
    build_manifest_out,
    generate_run_id,
    ingest_zip_archive,
    write_manifest_out,
)
from aquabit_ai.ingest.city_folder import (
    WideTimeseriesMatrix,
    discover_city_directories,
    ingest_city_directory,
    is_aquabit_city_directory,
    resolve_city_csv_route,
)
from aquabit_ai.ingest.inspector import inspect_aquabit_source
from aquabit_ai.ingest.legacy_single_csv import (
    ingest_legacy_analysis_csv,
    is_legacy_multisection_csv,
)


def ingest_any_source(
    source_path: str | Path,
    run_id: str | None = None,
) -> IngestionBundle:
    """Читает стандартный export.zip (§2), папку города (ADR-0007) или многосекционный legacy CSV (ADR-0006)."""
    p = Path(source_path)
    if p.is_dir():
        return ingest_city_directory(p, run_id=run_id)
    if is_legacy_multisection_csv(p):
        return ingest_legacy_analysis_csv(p, run_id=run_id)
    return ingest_zip_archive(p, run_id=run_id)


__all__ = [
    "IngestedCSVTable",
    "IngestionBundle",
    "WideTimeseriesMatrix",
    "build_manifest_out",
    "discover_city_directories",
    "generate_run_id",
    "ingest_any_source",
    "ingest_city_directory",
    "ingest_legacy_analysis_csv",
    "ingest_zip_archive",
    "inspect_aquabit_source",
    "is_aquabit_city_directory",
    "is_legacy_multisection_csv",
    "resolve_city_csv_route",
    "write_manifest_out",
]
