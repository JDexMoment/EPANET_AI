"""Подэтап 3.7 — Нормализация и контроль кросс-файловых связей строго через реестр ID (§4, п. 3.7, ADR-0007)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pyarrow as pa

from aquabit_ai.preprocess.errors import PreprocessingFatalError
from aquabit_ai.preprocess.log import PreprocessingLogger
from aquabit_ai.preprocess.s3_6_entity_registry import EntityRegistryEntry


STAGE_NAME = "3.7_cross_references"
LEGACY_ENDPOINT_PREFIXES: tuple[str, ...] = ("Узел ", "Источник ", "Резервуар ")
JUNCTION_TYPES = {"node", "source", "reservoir"}


def _arrow_str_list(series: pd.Series) -> list[str | None]:
    pa_arr = series.array._pa_array  # type: ignore[attr-defined]
    if isinstance(pa_arr, pa.ChunkedArray):
        pa_arr = pa_arr.combine_chunks()
    return [None if is_n else str(v) for is_n, v in zip(pa_arr.is_null().to_pylist(), pa_arr.to_pylist())]


def _strip_prefix(val: str | None) -> tuple[str | None, bool]:
    if val is None:
        return (None, False)
    for pfx in LEGACY_ENDPOINT_PREFIXES:
        if val.startswith(pfx):
            rest = val[len(pfx) :]
            return (None if rest == "" else rest, True)
        if val == pfx.strip():
            return (None, True)
    return (val, False)


def verify_and_normalize_cross_references(
    tables: dict[str, pd.DataFrame],
    entity_registry: dict[str, EntityRegistryEntry],
    logger: PreprocessingLogger,
    *,
    legacy_compat: bool = False,
    allow_broken_topology: bool = False,
    pruned_transit_node_ids: set[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Проверяет и нормализует все межтабличные ссылки строго по ID из реестра (§3.7)."""
    out_tables = {k: v.copy() for k, v in tables.items()}
    orphans: list[dict[str, Any]] = []
    tolerated_topology_orphans: list[dict[str, Any]] = []
    known_pruned_nodes = pruned_transit_node_ids or set()

    if legacy_compat:
        for link_file in ("pipes.csv", "pumps.csv", "valves.csv"):
            df = out_tables.get(link_file)
            if df is None or df.empty:
                continue
            for col in ("start_node_id", "end_node_id"):
                if col not in df.columns:
                    continue
                vals = _arrow_str_list(df[col])
                cleaned: list[str | None] = []
                changed = 0
                sample_pair: dict[str, str | None] | None = None
                for v in vals:
                    nv, was_stripped = _strip_prefix(v)
                    cleaned.append(nv)
                    if was_stripped:
                        changed += 1
                        if sample_pair is None:
                            sample_pair = {"before": v, "after": nv}
                if changed > 0:
                    df[col] = pd.Series(
                        pd.arrays.ArrowExtensionArray(pa.array(cleaned, type=pa.string())),
                        name=col,
                        index=df.index,
                    )
                    logger.record(
                        stage=STAGE_NAME,
                        operation="strip_legacy_endpoint_prefix",
                        file=link_file,
                        field=col,
                        before=sample_pair["before"] if sample_pair else None,
                        after=sample_pair["after"] if sample_pair else None,
                        affected_rows=changed,
                        severity="warning",
                    )

    valid_curve_ids: set[str] | None = None
    if "irregularity_curves.csv" in out_tables and "curve_id" in out_tables["irregularity_curves.csv"].columns:
        valid_curve_ids = {
            cid
            for cid in _arrow_str_list(out_tables["irregularity_curves.csv"]["curve_id"])
            if cid is not None
        }

    valid_qh_curve_ids: set[str] | None = None
    if "pump_curves.csv" in out_tables and "curve_id" in out_tables["pump_curves.csv"].columns:
        valid_qh_curve_ids = {
            cid
            for cid in _arrow_str_list(out_tables["pump_curves.csv"]["curve_id"])
            if cid is not None
        }

    def _check_fk(
        file_name: str,
        col_name: str,
        expected_types: set[str],
        *,
        allow_null: bool = False,
        is_link_topology_fk: bool = False,
    ) -> None:
        df = out_tables.get(file_name)
        if df is None or col_name not in df.columns:
            return
        vals = _arrow_str_list(df[col_name])
        target_bucket = (
            tolerated_topology_orphans
            if (is_link_topology_fk and allow_broken_topology)
            else orphans
        )
        for row_idx, ref_id in enumerate(vals):
            if ref_id is None:
                if not allow_null:
                    target_bucket.append(
                        {
                            "file": file_name,
                            "field": col_name,
                            "row_index": row_idx,
                            "orphan_id": None,
                            "reason": "null_foreign_key",
                        }
                    )
                continue
            entry = entity_registry.get(ref_id)
            if entry is None and ("node" in expected_types) and (ref_id in known_pruned_nodes):
                continue
            if entry is None or entry.type not in expected_types:
                target_bucket.append(
                    {
                        "file": file_name,
                        "field": col_name,
                        "row_index": row_idx,
                        "orphan_id": ref_id,
                        "expected_entity_types": sorted(expected_types),
                        "actual_entity_type": entry.type if entry else None,
                    }
                )

    for link_file in ("pipes.csv", "pumps.csv", "valves.csv"):
        _check_fk(link_file, "start_node_id", JUNCTION_TYPES, is_link_topology_fk=True)
        _check_fk(link_file, "end_node_id", JUNCTION_TYPES, is_link_topology_fk=True)

    _check_fk("sources.csv", "node_id", {"node"}, allow_null=True)
    _check_fk("reservoirs.csv", "node_id", {"node"}, allow_null=True)
    if "pump_curves.csv" in out_tables and "pump_id" in out_tables["pump_curves.csv"].columns:
        _check_fk("pump_curves.csv", "pump_id", {"pump"})
    elif valid_qh_curve_ids is not None and "pumps.csv" in out_tables:
        p_df = out_tables["pumps.csv"]
        if "curve_id" in p_df.columns:
            for row_idx, cid in enumerate(_arrow_str_list(p_df["curve_id"])):
                if cid is not None and cid not in valid_qh_curve_ids:
                    orphans.append(
                        {
                            "file": "pumps.csv",
                            "field": "curve_id",
                            "row_index": row_idx,
                            "orphan_id": cid,
                            "expected_entity_types": ["pump_curve"],
                        }
                    )

    _check_fk("demands.csv", "node_id", JUNCTION_TYPES)

    if valid_curve_ids is not None and "demands.csv" in out_tables:
        d_df = out_tables["demands.csv"]
        if "curve_id" in d_df.columns:
            for row_idx, cid in enumerate(_arrow_str_list(d_df["curve_id"])):
                if cid is not None and cid not in valid_curve_ids:
                    orphans.append(
                        {
                            "file": "demands.csv",
                            "field": "curve_id",
                            "row_index": row_idx,
                            "orphan_id": cid,
                            "expected_entity_types": ["irregularity_curve"],
                        }
                    )

    # Временные ряды длинного формата (§3.7)
    _check_fk("timeseries/node_pressure.csv", "id", JUNCTION_TYPES)
    _check_fk("timeseries/node_demand.csv", "id", JUNCTION_TYPES)
    _check_fk("timeseries/pipe_flow.csv", "id", {"pipe"})
    _check_fk("timeseries/pipe_velocity.csv", "id", {"pipe"})
    _check_fk("timeseries/pump_state.csv", "id", {"pump"})
    _check_fk("timeseries/reservoir_level.csv", "id", {"reservoir"})

    # Широкие матрицы R0..R1439 (ADR-0007)
    _check_fk("wide/node_head.csv", "id", JUNCTION_TYPES)
    _check_fk("wide/node_demand.csv", "id", JUNCTION_TYPES)
    _check_fk("wide/pipe_flow.csv", "id", {"pipe"})
    _check_fk("wide/pipe_velocity.csv", "id", {"pipe"})
    _check_fk("wide/valve_flow.csv", "id", {"valve"})
    _check_fk("wide/pump_flow.csv", "id", {"pump"})
    _check_fk("wide/pump_head.csv", "id", {"pump"})
    _check_fk("wide/reservoir_level.csv", "id", {"reservoir"})

    all_entity_types = {"node", "pipe", "source", "reservoir", "pump", "valve"}
    for rel_path in sorted(out_tables):
        if rel_path.startswith("charts/"):
            c_df = out_tables[rel_path]
            if "id" in c_df.columns:
                _check_fk(rel_path, "id", all_entity_types)

    if orphans:
        raise PreprocessingFatalError(
            "ORPHAN_REFERENCE",
            f"Нарушена ссылочная целостность: {len(orphans)} ссылок не найдены в реестре сущностей",
            examples=orphans[:25],
        )

    if tolerated_topology_orphans:
        logger.record(
            stage=STAGE_NAME,
            operation="allow_broken_link_topology_references",
            affected_rows=len(tolerated_topology_orphans),
            severity="warning",
            details={
                "tolerated_topology_orphans": len(tolerated_topology_orphans),
                "sample": tolerated_topology_orphans[:5],
            },
        )

    logger.record(
        stage=STAGE_NAME,
        operation="verify_cross_references",
        affected_rows=sum(len(df) for df in out_tables.values()),
        severity="info",
        details={
            "orphan_references_found": 0,
            "tolerated_topology_orphans": len(tolerated_topology_orphans),
        },
    )
    return out_tables
