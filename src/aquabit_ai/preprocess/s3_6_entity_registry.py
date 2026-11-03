"""Подэтап 3.6 — Построение единого реестра сущностей (ID registry, §4, п. 3.6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pyarrow as pa

from aquabit_ai.preprocess.errors import PreprocessingFatalError
from aquabit_ai.preprocess.log import PreprocessingLogger


STAGE_NAME = "3.6_entity_registry"

ENTITY_TABLE_TYPES: tuple[tuple[str, str], ...] = (
    ("nodes.csv", "node"),
    ("pipes.csv", "pipe"),
    ("sources.csv", "source"),
    ("reservoirs.csv", "reservoir"),
    ("pumps.csv", "pump"),
    ("valves.csv", "valve"),
)


@dataclass(frozen=True)
class EntityRegistryEntry:
    """Запись объекта сети в едином реестре ID (§3.6)."""

    type: str
    name: str | None
    source_file: str
    row_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "source_file": self.source_file,
            "row_index": self.row_index,
        }


def _arrow_str_list(series: pd.Series) -> list[str | None]:
    pa_arr = series.array._pa_array  # type: ignore[attr-defined]
    if isinstance(pa_arr, pa.ChunkedArray):
        pa_arr = pa_arr.combine_chunks()
    return [None if is_n else str(v) for is_n, v in zip(pa_arr.is_null().to_pylist(), pa_arr.to_pylist())]


def build_entity_registry(
    tables: dict[str, pd.DataFrame],
    logger: PreprocessingLogger,
) -> dict[str, EntityRegistryEntry]:
    """Строит глобальный реестр всех сетевых объектов по строковым ID (§3.6)."""
    registry: dict[str, EntityRegistryEntry] = {}
    counts_by_type: dict[str, int] = {}

    for rel_path, entity_type in ENTITY_TABLE_TYPES:
        df = tables.get(rel_path)
        if df is None or df.empty:
            continue
        if "id" not in df.columns:
            raise PreprocessingFatalError(
                "SCHEMA_MISMATCH",
                f"В таблице '{rel_path}' отсутствует каноническая колонка 'id'",
                file=rel_path,
                field="id",
            )

        ids = _arrow_str_list(df["id"])
        names = _arrow_str_list(df["name"]) if "name" in df.columns else [None] * len(ids)

        for row_idx, (oid, oname) in enumerate(zip(ids, names)):
            if oid is None or oid == "":
                raise PreprocessingFatalError(
                    "MANDATORY_FIELD_NULL",
                    f"Обнаружен null/пустой идентификатор 'id' в '{rel_path}' (row_index={row_idx})",
                    file=rel_path,
                    field="id",
                    examples=[{"row_index": row_idx, "file": rel_path}],
                )
            if oid in registry:
                prev = registry[oid]
                raise PreprocessingFatalError(
                    "DUPLICATE_ID",
                    f"Дублирующийся строковый ID '{oid}' в '{rel_path}' (row_index={row_idx}); "
                    f"ранее зарегистрирован в '{prev.source_file}' (row_index={prev.row_index})",
                    file=rel_path,
                    field="id",
                    examples=[
                        {
                            "id": oid,
                            "file": rel_path,
                            "row_index": row_idx,
                            "previous_file": prev.source_file,
                            "previous_row_index": prev.row_index,
                        }
                    ],
                )
            registry[oid] = EntityRegistryEntry(
                type=entity_type,
                name=oname,
                source_file=rel_path,
                row_index=row_idx,
            )
            counts_by_type[entity_type] = counts_by_type.get(entity_type, 0) + 1

    logger.record(
        stage=STAGE_NAME,
        operation="build_entity_registry",
        affected_rows=len(registry),
        severity="info",
        details={"total_entities": len(registry), "counts_by_type": counts_by_type},
    )
    return registry
