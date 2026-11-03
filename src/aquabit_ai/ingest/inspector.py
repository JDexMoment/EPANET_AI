"""Инспектор реальных выгрузок AquaBit (ZIP, папка города, многосекционный CSV или одиночный CSV)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aquabit_ai.config.csv_contracts import AliasRegistry, get_contract_for_path, is_wide_step_header
from aquabit_ai.ingest.archive import IngestionBundle, _read_raw_csv_bytes, ingest_zip_archive
from aquabit_ai.ingest.city_folder import ingest_city_directory, is_aquabit_city_directory
from aquabit_ai.ingest.legacy_single_csv import (
    ingest_legacy_analysis_csv,
    is_legacy_multisection_csv,
)


def _summarize_bundle_headers(
    bundle: IngestionBundle,
    source_type: str,
    registry: AliasRegistry,
) -> dict[str, Any]:
    files_summary = []
    for rel_path, table in sorted(bundle.tables.items()):
        contract = get_contract_for_path(rel_path)
        if contract is not None and contract.is_wide_timeseries and table.wide_matrix is not None:
            w = table.wide_matrix
            id_resolved = registry.resolve_table_headers([w.id_column_raw], contract)
            preview = (
                [w.id_column_raw, *w.step_columns[:3], "...", w.step_columns[-1]]
                if len(w.step_columns) > 4
                else table.raw_headers
            )
            files_summary.append(
                {
                    "file": rel_path,
                    "source_file": table.source_label,
                    "encoding": table.detected_encoding,
                    "has_bom": table.has_bom,
                    "delimiter": repr(table.detected_delimiter),
                    "rows": w.num_rows,
                    "wide_n_steps": w.n_steps,
                    "wide_metric": w.canonical_metric,
                    "raw_headers_preview": preview,
                    "mapped_headers": {
                        **id_resolved,
                        f"R0..R{w.n_steps - 1}": w.canonical_metric,
                    },
                    "unmapped_headers": [h for h, c in id_resolved.items() if c is None],
                }
            )
            continue

        non_step_headers = [h for h in table.raw_headers if not is_wide_step_header(h)]
        resolved = registry.resolve_table_headers(non_step_headers, contract)
        unmapped = [h for h, c in resolved.items() if c is None]
        files_summary.append(
            {
                "file": rel_path,
                "source_file": table.source_label,
                "encoding": table.detected_encoding,
                "has_bom": table.has_bom,
                "delimiter": repr(table.detected_delimiter),
                "rows": len(table.dataframe) if table.dataframe is not None else None,
                "raw_headers": table.raw_headers,
                "mapped_headers": resolved,
                "unmapped_headers": unmapped,
            }
        )
    return {
        "source": str(bundle.archive_path),
        "source_type": source_type,
        "has_manifest": bundle.manifest is not None,
        "ingestion_issues": [i.model_dump(mode="json") for i in bundle.ingestion_issues],
        "csv_files": files_summary,
    }


def inspect_aquabit_source(
    target_path: str | Path,
    aliases: AliasRegistry | None = None,
) -> dict[str, Any]:
    """Инспектирует заголовки, кодировки и разделители реальных CSV/ZIP/папок городов без изменения файлов."""
    registry = aliases or AliasRegistry.from_yaml()
    path = Path(target_path)

    if path.is_file() and path.suffix.lower() == ".zip":
        bundle = ingest_zip_archive(path)
        return _summarize_bundle_headers(bundle, "zip", registry)

    if path.is_file() and is_legacy_multisection_csv(path):
        bundle = ingest_legacy_analysis_csv(path)
        return _summarize_bundle_headers(bundle, "legacy_multisection_csv", registry)

    if path.is_dir() and is_aquabit_city_directory(path):
        bundle = ingest_city_directory(path)
        return _summarize_bundle_headers(bundle, "city_folder", registry)

    csv_paths: list[tuple[str, Path]] = []
    if path.is_file() and path.suffix.lower() in {".csv", ".tsv", ".txt"}:
        csv_paths.append((path.name, path))
    elif path.is_dir():
        for p in sorted(path.rglob("*.csv")):
            if is_legacy_multisection_csv(p):
                sub_bundle = ingest_legacy_analysis_csv(p)
                for vpath in sorted(sub_bundle.tables):
                    csv_paths.append((f"__MULTI__::{p.name}::{vpath}", p))
            else:
                csv_paths.append((p.relative_to(path).as_posix(), p))

    files_summary: list[dict[str, Any]] = []
    seen_multi_files: dict[Path, IngestionBundle] = {}
    for rel_path, csv_file in csv_paths:
        if rel_path.startswith("__MULTI__::"):
            _, fname, vpath = rel_path.split("::", 2)
            if csv_file not in seen_multi_files:
                seen_multi_files[csv_file] = ingest_legacy_analysis_csv(csv_file)
            tbl = seen_multi_files[csv_file].tables[vpath]
            contract = get_contract_for_path(vpath)
            resolved = registry.resolve_table_headers(tbl.raw_headers, contract)
            files_summary.append(
                {
                    "file": f"{fname}::{vpath}",
                    "encoding": tbl.detected_encoding,
                    "has_bom": tbl.has_bom,
                    "delimiter": repr(tbl.detected_delimiter),
                    "rows": len(tbl.dataframe) if tbl.dataframe is not None else None,
                    "raw_headers": tbl.raw_headers,
                    "mapped_headers": resolved,
                    "unmapped_headers": [h for h, c in resolved.items() if c is None],
                }
            )
            continue

        table = _read_raw_csv_bytes(rel_path, csv_file.read_bytes())
        contract = get_contract_for_path(rel_path)
        resolved = registry.resolve_table_headers(table.raw_headers, contract)
        unmapped = [h for h, c in resolved.items() if c is None]
        files_summary.append(
            {
                "file": rel_path,
                "encoding": table.detected_encoding,
                "has_bom": table.has_bom,
                "delimiter": repr(table.detected_delimiter),
                "rows": len(table.dataframe) if table.dataframe is not None else None,
                "raw_headers": table.raw_headers,
                "mapped_headers": resolved,
                "unmapped_headers": unmapped,
            }
        )

    return {
        "source": str(path),
        "source_type": "directory_or_csv",
        "csv_files": files_summary,
    }
