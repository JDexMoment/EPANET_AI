"""Отдельные проверки валидации Этапа 2 с явными кодами ошибок (§4, Этап 2, ADR-0007)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from aquabit_ai.config.csv_contracts import (
    AliasRegistry,
    TableContract,
    get_contract_for_path,
    is_wide_step_header,
)
from aquabit_ai.config.manifest import ExecutionMode
from aquabit_ai.config.validation_models import CheckCode, CheckSeverity, ValidationCheckItem
from aquabit_ai.ingest.archive import IngestedCSVTable, IngestionBundle


NULL_TOKENS = {"", "null", "NULL", "None"}
PREFIXED_ID_RE = re.compile(r"^([A-Za-zА-Яа-я]+)(\d+)$")


def _is_raw_null(val: str) -> bool:
    return val.strip() in NULL_TOKENS


LEGACY_ENDPOINT_PREFIXES: tuple[str, ...] = ("Узел ", "Источник ", "Резервуар ")


def _strip_legacy_endpoint_prefix(raw_ref: str) -> str:
    for pfx in LEGACY_ENDPOINT_PREFIXES:
        if raw_ref.startswith(pfx):
            return raw_ref[len(pfx) :]
        if raw_ref == pfx.strip():
            return ""
    return raw_ref


def _find_raw_col_for_canonical(
    df: pd.DataFrame,
    canonical_name: str,
    registry: AliasRegistry,
    contract: TableContract | None = None,
    allow_legacy_name_as_id: bool = False,
) -> str | None:
    resolved = registry.resolve_table_headers(list(df.columns), contract)
    for raw_col, can_col in resolved.items():
        if can_col == canonical_name:
            return raw_col
    if allow_legacy_name_as_id and canonical_name == "id":
        for raw_col, can_col in resolved.items():
            if can_col == "name":
                return raw_col
    return None


def check_encoding(
    bundle: IngestionBundle,
    strict: bool = True,
) -> ValidationCheckItem | None:
    """Проверка UTF-8 читаемости всех CSV-файлов (ENCODING_ERROR)."""
    bad_files: list[dict[str, Any]] = []
    has_undecodable = False

    for rel_path, table in sorted(bundle.tables.items()):
        if table.utf8_decode_error is not None:
            if table.detected_encoding is None:
                has_undecodable = True
            bad_files.append(
                {
                    "file": rel_path,
                    "source_file": table.source_label or rel_path,
                    "detected_encoding": table.detected_encoding or "unknown_binary",
                    "detail": table.utf8_decode_error,
                }
            )

    if not bad_files:
        return None

    severity: CheckSeverity = "fatal" if (strict or has_undecodable) else "warning"
    return ValidationCheckItem(
        code=CheckCode.ENCODING_ERROR,
        severity=severity,
        count=len(bad_files),
        message=(
            f"Обнаружены CSV-файлы не в кодировке UTF-8 ({len(bad_files)} шт.)"
            + ("" if severity == "fatal" else " — будет выполнена перекодировка на Этапе 3.1")
        ),
        developer_hint=(
            "Все CSV обязаны выгружаться в кодировке UTF-8 (допустим UTF-8 BOM) — §2."
        ),
        examples=bad_files[:15],
    )


def check_delimiters(
    bundle: IngestionBundle,
    strict: bool = True,
) -> ValidationCheckItem | None:
    """Проверка разделителя CSV: запятая ',', а не табуляция/точка с запятой (DELIMITER_MISMATCH)."""
    mismatches: list[dict[str, Any]] = []
    for rel_path, table in sorted(bundle.tables.items()):
        if table.detected_delimiter is not None and table.detected_delimiter != ",":
            mismatches.append(
                {
                    "file": rel_path,
                    "source_file": table.source_label or rel_path,
                    "expected_delimiter": ",",
                    "detected_delimiter": repr(table.detected_delimiter),
                }
            )

    if not mismatches:
        return None

    severity: CheckSeverity = "fatal" if strict else "warning"
    return ValidationCheckItem(
        code=CheckCode.DELIMITER_MISMATCH,
        severity=severity,
        count=len(mismatches),
        message=(
            f"Разделитель полей в {len(mismatches)} CSV-файлах отличается от запятой ','"
        ),
        developer_hint=(
            "Разработчику AquaBit: замените разделитель '\\t'/';' на запятую ',' (RFC 4180), "
            "а дробную часть чисел выводите через точку '.' (§2)."
        ),
        examples=mismatches[:15],
    )


def check_schemas(
    bundle: IngestionBundle,
    registry: AliasRegistry,
    strict: bool = True,
) -> ValidationCheckItem | None:
    """Проверка структуры CSV и наличия обязательных колонок (SCHEMA_MISMATCH)."""
    schema_errors: list[dict[str, Any]] = []

    for rel_path, table in sorted(bundle.tables.items()):
        if table.detected_encoding is None and table.utf8_decode_error is not None:
            continue

        if table.ragged_rows:
            for rag in table.ragged_rows[:5]:
                schema_errors.append({"reason": "ragged_row", **rag})
            continue

        if table.parse_error is not None:
            schema_errors.append(
                {
                    "file": rel_path,
                    "source_file": table.source_label or rel_path,
                    "reason": "csv_parse_error",
                    "detail": table.parse_error,
                }
            )
            continue

        header_counts = Counter(h.strip() for h in table.raw_headers)
        dup_headers = [h for h, cnt in header_counts.items() if cnt > 1 or h == ""]
        if dup_headers:
            schema_errors.append(
                {
                    "file": rel_path,
                    "reason": "duplicate_or_empty_header",
                    "headers": dup_headers[:20],
                }
            )

        contract = get_contract_for_path(rel_path)
        if contract is None:
            continue

        if contract.is_wide_timeseries:
            non_step = [h for h in table.raw_headers if not is_wide_step_header(h)]
            step_headers = [h for h in table.raw_headers if is_wide_step_header(h)]
            resolved_wide = registry.resolve_table_headers(non_step, contract)
            can_wide = {c for c in resolved_wide.values() if c is not None}
            missing_req = [r for r in contract.required_columns if r not in can_wide]
            if missing_req or not step_headers:
                schema_errors.append(
                    {
                        "file": rel_path,
                        "source_file": table.source_label or rel_path,
                        "reason": "invalid_wide_matrix_headers",
                        "missing_canonical_columns": missing_req,
                        "step_columns_found": len(step_headers),
                    }
                )
            continue

        resolved = registry.resolve_table_headers(table.raw_headers, contract)
        canonical_to_raw: dict[str, list[str]] = {}
        for raw_h, can_h in resolved.items():
            if can_h is not None:
                canonical_to_raw.setdefault(can_h, []).append(raw_h)

        collisions = {c: raws for c, raws in canonical_to_raw.items() if len(raws) > 1}
        if collisions:
            schema_errors.append(
                {
                    "file": rel_path,
                    "reason": "ambiguous_column_aliases",
                    "collisions": collisions,
                }
            )

        missing_required = [
            req for req in contract.required_columns if req not in canonical_to_raw
        ]
        if (
            not strict
            and contract.primary_id_column == "id"
            and "id" in missing_required
            and "name" in canonical_to_raw
        ):
            missing_required = [req for req in missing_required if req != "id"]

        if missing_required:
            schema_errors.append(
                {
                    "file": rel_path,
                    "source_file": table.source_label or rel_path,
                    "reason": "missing_required_columns",
                    "missing_canonical_columns": missing_required,
                    "actual_raw_headers": table.raw_headers,
                }
            )

        for any_group in contract.any_of_required_groups:
            if not any(candidate in canonical_to_raw for candidate in any_group):
                schema_errors.append(
                    {
                        "file": rel_path,
                        "source_file": table.source_label or rel_path,
                        "reason": "missing_any_of_required_columns",
                        "expected_any_of": list(any_group),
                        "actual_raw_headers": table.raw_headers,
                    }
                )

    if not schema_errors:
        return None

    return ValidationCheckItem(
        code=CheckCode.SCHEMA_MISMATCH,
        severity="fatal",
        count=len(schema_errors),
        message=f"Нарушена схема заголовков или геометрия строк CSV ({len(schema_errors)} нарушений)",
        developer_hint=(
            "Сверьте заголовки CSV со спецификацией §2 или зарегистрируйте легаси-заголовки "
            "в src/aquabit_ai/config/field_aliases.yaml."
        ),
        examples=schema_errors[:15],
    )


def check_unit_suffixes(
    bundle: IngestionBundle,
    registry: AliasRegistry,
) -> ValidationCheckItem | None:
    """Проверка наличия суффиксов единиц измерения в именах физических колонок (UNIT_SUFFIX_MISSING)."""
    BARE_METRIC_PREFIXES = (
        "head",
        "pressure",
        "flow",
        "demand",
        "velocity",
        "length",
        "diameter",
        "level",
        "elevation",
    )
    missing_units: list[dict[str, Any]] = []

    for rel_path, table in sorted(bundle.tables.items()):
        if not table.raw_headers:
            continue
        contract = get_contract_for_path(rel_path)

        if contract is not None and contract.is_wide_timeseries:
            # Для широкой матрицы R0..R1439 фиксируем одно сводное замечание об отсутствии единицы измерения
            missing_units.append(
                {
                    "file": rel_path,
                    "source_file": table.source_label or rel_path,
                    "raw_header": f"R0..R{max(0, len(table.raw_headers) - 2)}",
                    "canonical_target": contract.wide_metric_canonical,
                }
            )
            continue

        resolved = registry.resolve_table_headers(table.raw_headers, contract)

        for raw_h, can_h in resolved.items():
            cleaned = raw_h.strip()
            if not cleaned:
                continue
            if can_h is not None:
                fdef = registry.fields[can_h]
                if fdef.requires_unit_suffix and not registry.has_canonical_unit_suffix(cleaned):
                    missing_units.append(
                        {
                            "file": rel_path,
                            "source_file": table.source_label or rel_path,
                            "raw_header": raw_h,
                            "canonical_target": can_h,
                        }
                    )
            else:
                lower = cleaned.lower()
                if any(lower == p or lower.startswith(f"{p}_") for p in BARE_METRIC_PREFIXES):
                    if not registry.has_canonical_unit_suffix(cleaned):
                        missing_units.append(
                            {
                                "file": rel_path,
                                "raw_header": raw_h,
                                "canonical_target": None,
                            }
                        )

    if not missing_units:
        return None

    return ValidationCheckItem(
        code=CheckCode.UNIT_SUFFIX_MISSING,
        severity="warning",
        count=len(missing_units),
        message=(
            f"В {len(missing_units)} колонках/матрицах отсутствует канонический суффикс единицы измерения "
            "(_m, _m3_h, _mm, _bar, _m_s, _iso8601)"
        ),
        developer_hint=(
            "Рекомендуется передавать единицы измерения в суффиксе имени колонки (§1.8, §2); "
            "известные алиасы будут приведены к канону на Этапе 3.3."
        ),
        examples=missing_units[:20],
    )


def check_duplicate_ids(
    bundle: IngestionBundle,
    registry: AliasRegistry,
    strict: bool = True,
) -> ValidationCheckItem | None:
    """Проверка уникальности строковых ID внутри таблиц и между объектами сети (DUPLICATE_ID)."""
    ENTITY_FILES = (
        "nodes.csv",
        "pipes.csv",
        "sources.csv",
        "reservoirs.csv",
        "pumps.csv",
        "valves.csv",
    )
    duplicates: list[dict[str, Any]] = []
    global_owner: dict[str, tuple[str, int]] = {}

    for rel_path in ENTITY_FILES:
        table = bundle.tables.get(rel_path)
        if table is None or table.dataframe is None:
            continue
        contract = get_contract_for_path(rel_path)
        id_col = _find_raw_col_for_canonical(
            table.dataframe,
            "id",
            registry,
            contract,
            allow_legacy_name_as_id=not strict,
        )
        if id_col is None:
            continue

        seen_in_table: dict[str, int] = {}
        for idx, raw_id in enumerate(table.dataframe[id_col].tolist(), start=2):
            if _is_raw_null(raw_id):
                duplicates.append(
                    {
                        "file": rel_path,
                        "row_number": idx,
                        "id": raw_id,
                        "reason": "empty_or_null_id",
                    }
                )
                continue
            if raw_id in seen_in_table:
                duplicates.append(
                    {
                        "file": rel_path,
                        "row_number": idx,
                        "first_row_number": seen_in_table[raw_id],
                        "id": raw_id,
                        "reason": "duplicate_id_in_table",
                    }
                )
            else:
                seen_in_table[raw_id] = idx
                if raw_id in global_owner:
                    prev_file, prev_row = global_owner[raw_id]
                    duplicates.append(
                        {
                            "file": rel_path,
                            "row_number": idx,
                            "id": raw_id,
                            "collides_with_file": prev_file,
                            "collides_with_row": prev_row,
                            "reason": "duplicate_id_across_entity_tables",
                        }
                    )
                else:
                    global_owner[raw_id] = (rel_path, idx)

    # Если в demands.csv присутствует собственная колонка id (а не node_id) — проверяем её уникальность
    demands_table = bundle.tables.get("demands.csv")
    if demands_table is not None and demands_table.dataframe is not None:
        d_contract = get_contract_for_path("demands.csv")
        d_id_col = _find_raw_col_for_canonical(demands_table.dataframe, "id", registry, d_contract)
        if d_id_col is not None:
            seen_demand_ids: dict[str, int] = {}
            for idx, raw_id in enumerate(demands_table.dataframe[d_id_col].tolist(), start=2):
                if _is_raw_null(raw_id):
                    continue
                if raw_id in seen_demand_ids:
                    duplicates.append(
                        {
                            "file": "demands.csv",
                            "row_number": idx,
                            "first_row_number": seen_demand_ids[raw_id],
                            "id": raw_id,
                            "reason": "duplicate_id_in_table",
                        }
                    )
                else:
                    seen_demand_ids[raw_id] = idx

    # В широких временны́х матрицах каждая строка также должна иметь уникальный непустой ID объекта
    for rel_path, table in sorted(bundle.tables.items()):
        contract = get_contract_for_path(rel_path)
        if contract is None or not contract.is_wide_timeseries or table.dataframe is None:
            continue
        w_id_col = _find_raw_col_for_canonical(table.dataframe, "id", registry, contract)
        if w_id_col is None:
            continue
        seen_wide: dict[str, int] = {}
        for idx, raw_id in enumerate(table.dataframe[w_id_col].tolist(), start=2):
            if _is_raw_null(raw_id):
                duplicates.append(
                    {
                        "file": rel_path,
                        "source_file": table.source_label or rel_path,
                        "row_number": idx,
                        "id": raw_id,
                        "reason": "empty_or_null_id_in_wide_matrix",
                    }
                )
                continue
            if raw_id in seen_wide:
                duplicates.append(
                    {
                        "file": rel_path,
                        "source_file": table.source_label or rel_path,
                        "row_number": idx,
                        "first_row_number": seen_wide[raw_id],
                        "id": raw_id,
                        "reason": "duplicate_id_in_wide_matrix",
                    }
                )
            else:
                seen_wide[raw_id] = idx

    if not duplicates:
        return None

    return ValidationCheckItem(
        code=CheckCode.DUPLICATE_ID,
        severity="fatal",
        count=len(duplicates),
        message=f"Обнаружены дублирующиеся или пустые строковые ID объектов ({len(duplicates)} шт.)",
        developer_hint=(
            "Каждый узел, участок трубы, источник, насос, клапан и резервуар обязан иметь "
            "уникальный строковый идентификатор (§1.7, §2)."
        ),
        examples=duplicates[:20],
    )


def check_irregularity_curves(
    bundle: IngestionBundle,
    registry: AliasRegistry,
) -> ValidationCheckItem | None:
    """Проверка уникальности и корректности ID кривых неравномерности (DUPLICATE_CURVE_ID)."""
    table = bundle.tables.get("irregularity_curves.csv")
    if table is None or table.dataframe is None:
        return None

    contract = get_contract_for_path("irregularity_curves.csv")
    df = table.dataframe
    curve_col = _find_raw_col_for_canonical(df, "curve_id", registry, contract)
    if curve_col is None:
        return None

    step_col = _find_raw_col_for_canonical(df, "step_index", registry, contract)
    if step_col is None:
        step_col = _find_raw_col_for_canonical(df, "time_iso8601", registry, contract)

    issues: list[dict[str, Any]] = []
    seen_keys: dict[tuple[str, ...], int] = {}
    reported_malformed_ids: set[str] = set()

    for idx, row in enumerate(df.to_dict(orient="records"), start=2):
        cid = str(row[curve_col])
        if _is_raw_null(cid):
            issues.append(
                {
                    "file": "irregularity_curves.csv",
                    "row_number": idx,
                    "curve_id": cid,
                    "reason": "empty_curve_id",
                }
            )
            continue

        if cid.endswith(":") and cid not in reported_malformed_ids:
            reported_malformed_ids.add(cid)
            issues.append(
                {
                    "file": "irregularity_curves.csv",
                    "row_number": idx,
                    "curve_id": cid,
                    "reason": "malformed_placeholder_curve_id_colon",
                }
            )

        if step_col is not None:
            step_val = str(row[step_col])
            composite_key = (cid, step_val)
            if composite_key in seen_keys:
                issues.append(
                    {
                        "file": "irregularity_curves.csv",
                        "row_number": idx,
                        "first_row_number": seen_keys[composite_key],
                        "curve_id": cid,
                        "step": step_val,
                        "reason": "duplicate_curve_step_entry",
                    }
                )
            else:
                seen_keys[composite_key] = idx
        else:
            single_key = (cid,)
            if single_key in seen_keys:
                issues.append(
                    {
                        "file": "irregularity_curves.csv",
                        "row_number": idx,
                        "first_row_number": seen_keys[single_key],
                        "curve_id": cid,
                        "reason": "duplicate_curve_id_without_step_column",
                    }
                )
            else:
                seen_keys[single_key] = idx

    if not issues:
        return None

    return ValidationCheckItem(
        code=CheckCode.DUPLICATE_CURVE_ID,
        severity="fatal",
        count=len(issues),
        message=(
            f"Нарушена уникальность или формат ID кривых неравномерности ({len(issues)} проблем)"
        ),
        developer_hint=(
            "Каждая суточная кривая в irregularity_curves.csv / График потребления.csv должна "
            "иметь уникальный ID (без технических префиксов вида '1:') и уникальные шаги (§2)."
        ),
        examples=issues[:20],
    )


def check_self_loop_links(
    bundle: IngestionBundle,
    registry: AliasRegistry,
    strict: bool = True,
    allow_broken_topology: bool = False,
) -> ValidationCheckItem | None:
    """Проверка участков-петель Начало == Конец в Труба/Насос/Клапан (SELF_LOOP_LINK, ADR-0007).

    Специально диагностирует баг выгрузки папок городов AquaBit, когда для участка e702 / p1263 / v1284
    в поля Начало и Конец ошибочно записан 'c702' / 'c1263' / 'c1284' вместо ID начального и конечного узлов.
    """
    loops: list[dict[str, Any]] = []
    mirrored_own_id_count = 0

    for link_file in ("pipes.csv", "pumps.csv", "valves.csv"):
        table = bundle.tables.get(link_file)
        if table is None or table.dataframe is None or table.dataframe.empty:
            continue
        contract = get_contract_for_path(link_file)
        df = table.dataframe
        id_col = _find_raw_col_for_canonical(
            df, "id", registry, contract, allow_legacy_name_as_id=not strict
        )
        s_col = _find_raw_col_for_canonical(df, "start_node_id", registry, contract)
        e_col = _find_raw_col_for_canonical(df, "end_node_id", registry, contract)
        if s_col is None or e_col is None:
            continue

        ids = df[id_col].tolist() if id_col else [""] * len(df)
        starts = df[s_col].tolist()
        ends = df[e_col].tolist()

        for row_idx, (lid, s_val, e_val) in enumerate(zip(ids, starts, ends), start=2):
            s_clean = (
                _strip_legacy_endpoint_prefix(s_val) if not strict else s_val
            ).strip()
            e_clean = (
                _strip_legacy_endpoint_prefix(e_val) if not strict else e_val
            ).strip()
            if s_clean in NULL_TOKENS or e_clean in NULL_TOKENS:
                continue
            if s_clean == e_clean:
                m_own = PREFIXED_ID_RE.match(lid.strip())
                m_end = PREFIXED_ID_RE.match(s_clean)
                is_exporter_cast_bug = bool(
                    m_own and m_end and m_own.group(2) == m_end.group(2) and m_own.group(1) != m_end.group(1)
                )
                if is_exporter_cast_bug:
                    mirrored_own_id_count += 1
                loops.append(
                    {
                        "file": link_file,
                        "source_file": table.source_label or link_file,
                        "row_number": row_idx,
                        "link_id": lid,
                        "start_node_id": s_val,
                        "end_node_id": e_val,
                        "exporter_own_id_cast_bug": is_exporter_cast_bug,
                    }
                )

    if not loops:
        return None

    severity: CheckSeverity = "warning" if allow_broken_topology else "fatal"
    bug_note = (
        f" (в {mirrored_own_id_count} из {len(loops)} строк в Начало и Конец выгружен собственный номер "
        "участка с префиксом 'c', например e702 -> c702,c702)"
        if mirrored_own_id_count > 0
        else ""
    )
    return ValidationCheckItem(
        code=CheckCode.SELF_LOOP_LINK,
        severity=severity,
        count=len(loops),
        message=(
            f"Обнаружены вырожденные участки-петли (Начало == Конец): {len(loops)} шт.{bug_note}"
        ),
        developer_hint=(
            "КРИТИЧЕСКИЙ БАГ ЭКСПОРТА AQUABIT: в таблицах Труба.csv, Насос.csv и Клапан.csv "
            "поля 'Начало' и 'Конец' содержат одинаковый ID ('c' + ID самого элемента: e702 -> c702,c702; "
            "p1263 -> c1263,c1263; v1284 -> c1284,c1284). Необходимо выгружать реальные строковые ID "
            "начального и конечного узлов из таблицы Узел.csv / Источники.csv."
        ),
        examples=loops[:20],
    )


def _extract_id_set(
    bundle: IngestionBundle,
    rel_path: str,
    canonical_col: str,
    registry: AliasRegistry,
    allow_legacy_name_as_id: bool = False,
) -> set[str] | None:
    table = bundle.tables.get(rel_path)
    if table is None or table.dataframe is None:
        return None
    contract = get_contract_for_path(rel_path)
    raw_col = _find_raw_col_for_canonical(
        table.dataframe,
        canonical_col,
        registry,
        contract,
        allow_legacy_name_as_id=allow_legacy_name_as_id,
    )
    if raw_col is None:
        return None
    return {v for v in table.dataframe[raw_col].tolist() if not _is_raw_null(v)}


def check_orphan_references(
    bundle: IngestionBundle,
    registry: AliasRegistry,
    strict: bool = True,
    allow_broken_topology: bool = False,
) -> ValidationCheckItem | None:
    """Проверка ссылочной целостности между таблицами по строковым ID (ORPHAN_REFERENCE)."""
    allow_legacy = not strict
    node_ids = _extract_id_set(bundle, "nodes.csv", "id", registry, allow_legacy)
    if node_ids is None:
        return None

    source_ids = _extract_id_set(bundle, "sources.csv", "id", registry, allow_legacy) or set()
    reservoir_ids = _extract_id_set(bundle, "reservoirs.csv", "id", registry, allow_legacy) or set()
    pipe_ids = _extract_id_set(bundle, "pipes.csv", "id", registry, allow_legacy) or set()
    pump_ids = _extract_id_set(bundle, "pumps.csv", "id", registry, allow_legacy) or set()
    valve_ids = _extract_id_set(bundle, "valves.csv", "id", registry, allow_legacy) or set()
    curve_ids = _extract_id_set(bundle, "irregularity_curves.csv", "curve_id", registry)
    qh_curve_ids = _extract_id_set(bundle, "pump_curves.csv", "curve_id", registry)

    valid_junction_ids = node_ids | source_ids | reservoir_ids | bundle.pruned_transit_node_ids

    orphans: list[dict[str, Any]] = []
    non_topology_orphans = 0

    def _verify_fk_column(
        file_name: str,
        canonical_col: str,
        allowed_ids: set[str],
        target_desc: str,
        allow_null: bool = False,
        strip_endpoint_prefix: bool = False,
        is_link_topology_fk: bool = False,
    ) -> None:
        nonlocal non_topology_orphans
        table = bundle.tables.get(file_name)
        if table is None or table.dataframe is None:
            return
        contract = get_contract_for_path(file_name)
        raw_col = _find_raw_col_for_canonical(table.dataframe, canonical_col, registry, contract)
        if raw_col is None:
            return
        for row_idx, ref_val in enumerate(table.dataframe[raw_col].tolist(), start=2):
            candidate = (
                _strip_legacy_endpoint_prefix(ref_val)
                if (strip_endpoint_prefix and allow_legacy)
                else ref_val
            )
            if _is_raw_null(candidate):
                if not allow_null:
                    if not is_link_topology_fk:
                        non_topology_orphans += 1
                    orphans.append(
                        {
                            "file": file_name,
                            "source_file": table.source_label or file_name,
                            "row_number": row_idx,
                            "column": raw_col,
                            "orphan_id": ref_val,
                            "expected_in": target_desc,
                        }
                    )
                continue
            if candidate not in allowed_ids:
                if not is_link_topology_fk:
                    non_topology_orphans += 1
                orphans.append(
                    {
                        "file": file_name,
                        "source_file": table.source_label or file_name,
                        "row_number": row_idx,
                        "column": raw_col,
                        "orphan_id": ref_val,
                        "expected_in": target_desc,
                    }
                )

    for link_file in ("pipes.csv", "pumps.csv", "valves.csv"):
        _verify_fk_column(
            link_file,
            "start_node_id",
            valid_junction_ids,
            "nodes/sources/reservoirs",
            strip_endpoint_prefix=True,
            is_link_topology_fk=True,
        )
        _verify_fk_column(
            link_file,
            "end_node_id",
            valid_junction_ids,
            "nodes/sources/reservoirs",
            strip_endpoint_prefix=True,
            is_link_topology_fk=True,
        )

    _verify_fk_column("demands.csv", "node_id", valid_junction_ids, "nodes/sources/reservoirs")
    if curve_ids is not None:
        _verify_fk_column(
            "demands.csv",
            "curve_id",
            curve_ids,
            "irregularity_curves.csv",
            allow_null=True,
        )

    if "pumps.csv" in bundle.tables:
        _verify_fk_column("pump_curves.csv", "pump_id", pump_ids, "pumps.csv")
        # В формате папок городов (ADR-0007) Насос.Кривая насоса ссылается на Кривая QH.ID (curve_id)
        pump_curves_tbl = bundle.tables.get("pump_curves.csv")
        has_pump_id_col = (
            pump_curves_tbl is not None
            and pump_curves_tbl.dataframe is not None
            and _find_raw_col_for_canonical(
                pump_curves_tbl.dataframe,
                "pump_id",
                registry,
                get_contract_for_path("pump_curves.csv"),
            )
            is not None
        )
        if not has_pump_id_col and qh_curve_ids is not None:
            _verify_fk_column(
                "pumps.csv",
                "curve_id",
                qh_curve_ids,
                "pump_curves.csv (Кривая QH)",
                allow_null=True,
            )

    # Временные ряды длинного формата -> реестр объектов (§3.7)
    _verify_fk_column(
        "timeseries/node_pressure.csv", "id", valid_junction_ids, "nodes/sources/reservoirs"
    )
    _verify_fk_column(
        "timeseries/node_demand.csv", "id", valid_junction_ids, "nodes/sources/reservoirs"
    )
    if "pipes.csv" in bundle.tables:
        _verify_fk_column("timeseries/pipe_flow.csv", "id", pipe_ids, "pipes.csv")
        _verify_fk_column("timeseries/pipe_velocity.csv", "id", pipe_ids, "pipes.csv")
    if "pumps.csv" in bundle.tables:
        _verify_fk_column("timeseries/pump_state.csv", "id", pump_ids, "pumps.csv")
    if "reservoirs.csv" in bundle.tables:
        _verify_fk_column("timeseries/reservoir_level.csv", "id", reservoir_ids, "reservoirs.csv")

    # Широкие матрицы R0..R1439 -> реестр соответствующих объектов (ADR-0007)
    _verify_fk_column("wide/node_head.csv", "id", valid_junction_ids, "nodes/sources/reservoirs")
    _verify_fk_column("wide/node_demand.csv", "id", valid_junction_ids, "nodes/sources/reservoirs")
    if "pipes.csv" in bundle.tables:
        _verify_fk_column("wide/pipe_flow.csv", "id", pipe_ids, "pipes.csv")
        _verify_fk_column("wide/pipe_velocity.csv", "id", pipe_ids, "pipes.csv")
    if "valves.csv" in bundle.tables:
        _verify_fk_column("wide/valve_flow.csv", "id", valve_ids, "valves.csv")
    if "pumps.csv" in bundle.tables:
        _verify_fk_column("wide/pump_flow.csv", "id", pump_ids, "pumps.csv")
        _verify_fk_column("wide/pump_head.csv", "id", pump_ids, "pumps.csv")
    if "reservoirs.csv" in bundle.tables:
        _verify_fk_column("wide/reservoir_level.csv", "id", reservoir_ids, "reservoirs.csv")

    if not orphans:
        return None

    severity: CheckSeverity = (
        "warning" if (allow_broken_topology and non_topology_orphans == 0) else "fatal"
    )
    return ValidationCheckItem(
        code=CheckCode.ORPHAN_REFERENCE,
        severity=severity,
        count=len(orphans),
        message=f"Обнаружены осиротевшие ссылки между таблицами ({len(orphans)} шт.)",
        developer_hint=(
            "Все ссылки start_node_id (Начало), end_node_id (Конец), node_id, curve_id и ID "
            "во временных рядах должны точно совпадать со строковыми ID объектов в базовых таблицах (§1.7, §3.7)."
        ),
        examples=orphans[:25],
    )


def check_pump_curves_completeness(
    bundle: IngestionBundle,
    registry: AliasRegistry,
    strict: bool = True,
) -> tuple[ValidationCheckItem | None, list[str]]:
    """Проверка полноты Q-H кривых насосов: минимум 3 точки на каждый насос/кривую (PUMP_CURVE_INCOMPLETE)."""
    pumps_table = bundle.tables.get("pumps.csv")
    if pumps_table is None or pumps_table.dataframe is None or pumps_table.dataframe.empty:
        return (None, [])

    pumps_contract = get_contract_for_path("pumps.csv")
    pump_id_col = _find_raw_col_for_canonical(
        pumps_table.dataframe,
        "id",
        registry,
        pumps_contract,
        allow_legacy_name_as_id=not strict,
    )
    if pump_id_col is None:
        return (None, [])

    pump_curve_fk_col = _find_raw_col_for_canonical(
        pumps_table.dataframe,
        "curve_id",
        registry,
        pumps_contract,
    )

    declared_pumps: list[tuple[str, str | None]] = []
    for row in pumps_table.dataframe.to_dict(orient="records"):
        pid = str(row[pump_id_col])
        if _is_raw_null(pid):
            continue
        cid_ref = str(row[pump_curve_fk_col]).strip() if pump_curve_fk_col else ""
        declared_pumps.append((pid, None if cid_ref in NULL_TOKENS else cid_ref))

    if not declared_pumps:
        return (None, [])

    by_pump_counts: Counter[str] = Counter()
    by_curve_counts: Counter[str] = Counter()

    curves_table = bundle.tables.get("pump_curves.csv")
    if curves_table is not None and curves_table.dataframe is not None:
        c_contract = get_contract_for_path("pump_curves.csv")
        cdf = curves_table.dataframe
        c_pump_col = _find_raw_col_for_canonical(cdf, "pump_id", registry, c_contract)
        c_curve_col = _find_raw_col_for_canonical(cdf, "curve_id", registry, c_contract)
        c_q_col = _find_raw_col_for_canonical(cdf, "flow_m3_h", registry, c_contract)
        c_h_col = _find_raw_col_for_canonical(cdf, "head_m", registry, c_contract)

        if c_q_col and c_h_col:
            for row in cdf.to_dict(orient="records"):
                q_raw = str(row[c_q_col])
                h_raw = str(row[c_h_col])
                if _is_raw_null(q_raw) or _is_raw_null(h_raw):
                    continue
                if c_pump_col:
                    pid_val = str(row[c_pump_col])
                    if not _is_raw_null(pid_val):
                        by_pump_counts[pid_val] += 1
                if c_curve_col:
                    cid_val = str(row[c_curve_col])
                    if not _is_raw_null(cid_val):
                        by_curve_counts[cid_val] += 1

    incomplete: list[dict[str, Any]] = []
    blocked_ids: list[str] = []
    for pid, cid_ref in declared_pumps:
        pts_pump = by_pump_counts.get(pid, 0)
        pts_curve = by_curve_counts.get(cid_ref, 0) if cid_ref else 0
        pts = max(pts_pump, pts_curve)
        if pts < 3:
            blocked_ids.append(pid)
            incomplete.append(
                {
                    "pump_id": pid,
                    "curve_id": cid_ref,
                    "points_found": pts,
                    "minimum_required": 3,
                }
            )

    if not incomplete:
        return (None, [])

    return (
        ValidationCheckItem(
            code=CheckCode.PUMP_CURVE_INCOMPLETE,
            severity="warning",
            count=len(incomplete),
            message=(
                f"Для {len(incomplete)} насосов паспортная Q-H кривая содержит менее 3 точек — "
                "анализ принадлежности рабочей точки кривой для них заблокирован"
            ),
            developer_hint=(
                "Выгружайте полную Q-H кривую (минимум 3 точки на каждый насос/кривую) в Кривая QH.csv / pump_curves.csv (§2)."
            ),
            examples=incomplete[:20],
        ),
        blocked_ids,
    )


def check_missing_entity_names(
    bundle: IngestionBundle,
    registry: AliasRegistry,
) -> ValidationCheckItem | None:
    """Предупреждение для папок городов: выгружен внутренний ID без человекочитаемого поля 'Название'."""
    if bundle.manifest is None or bundle.manifest.aquabit_version != "city_folder_csv_13":
        return None

    missing_name_tables: list[dict[str, Any]] = []
    for rel_path in ("nodes.csv", "pipes.csv", "sources.csv", "pumps.csv", "valves.csv"):
        table = bundle.tables.get(rel_path)
        if table is None or table.dataframe is None:
            continue
        contract = get_contract_for_path(rel_path)
        name_col = _find_raw_col_for_canonical(table.dataframe, "name", registry, contract)
        if name_col is None:
            missing_name_tables.append(
                {
                    "file": rel_path,
                    "source_file": table.source_label or rel_path,
                    "present_headers": table.raw_headers,
                }
            )

    if not missing_name_tables:
        return None

    return ValidationCheckItem(
        code=CheckCode.MISSING_ENTITY_NAMES,
        severity="warning",
        count=len(missing_name_tables),
        message=(
            f"В {len(missing_name_tables)} статических таблицах выгружен только внутренний ID без диспетчерского поля 'Название'"
        ),
        developer_hint=(
            "Добавьте колонку 'Название' (например: 'НС Свобода агр1', 'ВЗУ-1', 'XY4973') в статические "
            "справочники Узел.csv, Труба.csv, Источники.csv, Насос.csv, Клапан.csv — это увеличит объём "
            "экспорта менее чем на 0.2%, но сделает инженерные отчёты читаемыми для эксплуатационщиков."
        ),
        examples=missing_name_tables,
    )


def check_id_prefixes(
    bundle: IngestionBundle,
    registry: AliasRegistry,
) -> ValidationCheckItem | None:
    """Проверка буквенных префиксов классов объектов в папках городов (ADR-0008):
    Узел -> c, Труба -> e, Насос -> p, Клапан -> v, Кривая QH -> u, График потребления -> t.
    """
    if bundle.manifest is None or bundle.manifest.aquabit_version != "city_folder_csv_13":
        return None

    PREFIX_RULES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
        ("nodes.csv", "id", ("c",), "Узел (c)"),
        ("pipes.csv", "id", ("e",), "Труба (e)"),
        ("sources.csv", "id", ("e", "c"), "Источник (e/c)"),
        ("pumps.csv", "id", ("p",), "Насос (p)"),
        ("pumps.csv", "curve_id", ("u",), "Кривая QH насоса (u)"),
        ("valves.csv", "id", ("v",), "Клапан (v)"),
        ("pump_curves.csv", "curve_id", ("u",), "Кривая QH (u)"),
        ("irregularity_curves.csv", "curve_id", ("t",), "График потребления (t)"),
        ("demands.csv", "node_id", ("c",), "Узел потребителя (c)"),
        ("demands.csv", "curve_id", ("t",), "График потребления (t)"),
        ("wide/node_head.csv", "id", ("c", "e"), "Напор Узел (c)"),
        ("wide/node_demand.csv", "id", ("c",), "Потребление Узел (c)"),
        ("wide/pipe_flow.csv", "id", ("e",), "Поток Труба (e)"),
        ("wide/pump_flow.csv", "id", ("p",), "Поток Насос (p)"),
        ("wide/valve_flow.csv", "id", ("v",), "Поток Клапан (v)"),
    )

    mismatches: list[dict[str, Any]] = []
    for rel_path, canonical_col, allowed_pfxs, label_ru in PREFIX_RULES:
        table = bundle.tables.get(rel_path)
        if table is None or table.dataframe is None or table.dataframe.empty:
            continue
        contract = get_contract_for_path(rel_path)
        raw_col = _find_raw_col_for_canonical(table.dataframe, canonical_col, registry, contract)
        if raw_col is None:
            continue
        for row_idx, val in enumerate(table.dataframe[raw_col].tolist(), start=2):
            s = str(val).strip()
            if s in NULL_TOKENS:
                continue
            if not any(s.startswith(pfx) for pfx in allowed_pfxs):
                mismatches.append(
                    {
                        "file": rel_path,
                        "source_file": table.source_label or rel_path,
                        "row_number": row_idx,
                        "column": raw_col,
                        "actual_id": s,
                        "expected_prefix": allowed_pfxs,
                        "object_class": label_ru,
                    }
                )

    if not mismatches:
        return None

    return ValidationCheckItem(
        code=CheckCode.ID_PREFIX_MISMATCH,
        severity="error",
        count=len(mismatches),
        message=(
            f"Нарушены буквенные префиксы классов объектов ({len(mismatches)} строк): "
            "ожидается Узел='c', Труба='e', Насос='p', Клапан='v', Кривая QH='u', График='t'"
        ),
        developer_hint=(
            "Проверьте соответствие строковых префиксов ID классу объекта (ADR-0008): "
            "c — узел, e — труба, p — насос, v — клапан, u — кривая QH, t — график потребления."
        ),
        examples=mismatches[:20],
    )


def check_schedule_24_steps(
    bundle: IngestionBundle,
    registry: AliasRegistry,
) -> ValidationCheckItem | None:
    """Проверка График потребления.csv: каждый ID графика (t*) обязан иметь ровно 24 часовых значения (ADR-0008)."""
    if bundle.manifest is None or bundle.manifest.aquabit_version != "city_folder_csv_13":
        return None

    table = bundle.tables.get("irregularity_curves.csv")
    if table is None or table.dataframe is None or table.dataframe.empty:
        return None

    contract = get_contract_for_path("irregularity_curves.csv")
    curve_col = _find_raw_col_for_canonical(table.dataframe, "curve_id", registry, contract)
    if curve_col is None:
        return None

    counts: Counter[str] = Counter()
    for cid in table.dataframe[curve_col].tolist():
        s = str(cid).strip()
        if s not in NULL_TOKENS:
            counts[s] += 1

    bad_schedules = [
        {
            "file": "irregularity_curves.csv",
            "source_file": table.source_label or "График потребления.csv",
            "curve_id": cid,
            "rows_found": cnt,
            "expected_rows": 24,
        }
        for cid, cnt in sorted(counts.items())
        if cnt != 24
    ]
    if not bad_schedules:
        return None

    return ValidationCheckItem(
        code=CheckCode.SCHEDULE_STEPS_NOT_24,
        severity="warning",
        count=len(bad_schedules),
        message=(
            f"В График потребления.csv обнаружены графики с числом часовых точек != 24 ({len(bad_schedules)} шт.)"
        ),
        developer_hint=(
            "По спецификации AquaBit (ADR-0008) каждый ID в 'График потребления.csv' (t*) должен "
            "содержать ровно 24 строки — по одному часовому коэффициенту на каждый час суток."
        ),
        examples=bad_schedules[:20],
    )


def check_required_pressure_norm(
    bundle: IngestionBundle,
    registry: AliasRegistry,
) -> ValidationCheckItem | None:
    """Проверка положительных значений 'Требуемое давление' по нормативу СП 31.13330.2021 (10 + 4*(n-1) м)."""
    table = bundle.tables.get("nodes.csv")
    if table is None or table.dataframe is None or table.dataframe.empty:
        return None

    contract = get_contract_for_path("nodes.csv")
    id_col = _find_raw_col_for_canonical(table.dataframe, "id", registry, contract)
    req_col = _find_raw_col_for_canonical(
        table.dataframe, "required_pressure_m", registry, contract
    )
    if req_col is None:
        return None

    ids = table.dataframe[id_col].tolist() if id_col else [""] * len(table.dataframe)
    reqs = table.dataframe[req_col].tolist()
    abnormal: list[dict[str, Any]] = []

    for row_idx, (nid, r_raw) in enumerate(zip(ids, reqs), start=2):
        s = str(r_raw).strip()
        if s in NULL_TOKENS:
            continue
        try:
            val = float(s)
        except ValueError:
            continue
        # 0.0 — промежуточный узел без абонентов; положительный требуемый напор сравниваем с нормативом >= 10 м
        if val < 0.0 or (0.0 < val < 10.0) or val > 120.0:
            abnormal.append(
                {
                    "file": "nodes.csv",
                    "source_file": table.source_label or "nodes.csv",
                    "row_number": row_idx,
                    "node_id": nid,
                    "required_pressure_m": val,
                    "norm_reference": "10 м (1 этаж) + 4 м на каждый последующий этаж (СП 31.13330.2021)",
                }
            )

    if not abnormal:
        return None

    return ValidationCheckItem(
        code=CheckCode.ABNORMAL_REQUIRED_PRESSURE,
        severity="warning",
        count=len(abnormal),
        message=(
            f"Обнаружены нетипичные значения требуемого давления (<10 м при ненулевом задании или >120 м): "
            f"{len(abnormal)} узлов"
        ),
        developer_hint=(
            "В отечественной практике минимальное требуемое давление для 1-этажной застройки составляет 10 м "
            "+ 4 м на каждый следующий этаж (10, 14, 18, 22, 26... м), а для промежуточных узлов — 0 (не задано)."
        ),
        examples=abnormal[:20],
    )


def _count_nonzero_numeric_values(table: IngestedCSVTable | None, raw_col: str | None) -> int:
    if table is None or table.dataframe is None or raw_col is None:
        return 0
    nonzero = 0
    for val in table.dataframe[raw_col].tolist():
        s = val.strip()
        if s in NULL_TOKENS:
            continue
        try:
            num = float(s)
        except ValueError:
            continue
        if abs(num) > 0.0:
            nonzero += 1
    return nonzero


def _count_nonzero_wide_matrix(table: IngestedCSVTable | None) -> int:
    if table is None or table.wide_matrix is None:
        return 0
    mat, null_mask = table.wide_matrix.to_numpy_with_null_mask()
    valid_nonzero = (~null_mask) & (~np.isnan(mat)) & (np.abs(mat) > 0.0)
    return int(np.count_nonzero(valid_nonzero))


def check_mode_consistency(
    bundle: IngestionBundle,
    requested_mode: ExecutionMode,
    registry: AliasRegistry,
) -> tuple[ValidationCheckItem | None, ExecutionMode, bool]:
    """Проверка согласованности режима results/no_results с фактическим наличием напоров (§4, Этап 2)."""
    ts_pressure = bundle.tables.get("timeseries/node_pressure.csv")
    ts_contract = get_contract_for_path("timeseries/node_pressure.csv")
    ts_head_col = (
        _find_raw_col_for_canonical(ts_pressure.dataframe, "head_m", registry, ts_contract)
        if ts_pressure and ts_pressure.dataframe is not None
        else None
    )
    nonzero_ts_heads = _count_nonzero_numeric_values(ts_pressure, ts_head_col)
    nonzero_wide_heads = _count_nonzero_wide_matrix(bundle.tables.get("wide/node_head.csv"))

    nodes_table = bundle.tables.get("nodes.csv")
    nodes_contract = get_contract_for_path("nodes.csv")
    nodes_calc_col = (
        _find_raw_col_for_canonical(
            nodes_table.dataframe, "calculated_head_m", registry, nodes_contract
        )
        if nodes_table and nodes_table.dataframe is not None
        else None
    )
    nonzero_node_heads = _count_nonzero_numeric_values(nodes_table, nodes_calc_col)

    total_nonzero_heads = nonzero_ts_heads + nonzero_wide_heads + nonzero_node_heads
    calc_status = bundle.manifest.calculation.status if bundle.manifest is not None else None

    if requested_mode == "results":
        has_valid_calc = (calc_status in {None, "performed"}) and (total_nonzero_heads > 0)
        if not has_valid_calc:
            return (
                ValidationCheckItem(
                    code=CheckCode.NO_RESULTS_BUT_MODE_RESULTS,
                    severity="error",
                    count=1,
                    message=(
                        "Запрошен режим mode='results', но выполненные гидравлические результаты "
                        f"(ненулевые напоры) отсутствуют (calculation.status={calc_status!r}, "
                        f"nonzero_heads={total_nonzero_heads}). Выполнено автоматическое "
                        "переключение в mode='no_results'."
                    ),
                    developer_hint=(
                        "Выполните гидравлический расчёт в AquaBit перед экспортом либо запускайте "
                        "модуль в режиме диагностики готовности mode='no_results'."
                    ),
                    examples=[
                        {
                            "requested_mode": "results",
                            "switched_to": "no_results",
                            "calculation_status": calc_status,
                            "nonzero_timeseries_heads": nonzero_ts_heads + nonzero_wide_heads,
                            "nonzero_node_calculated_heads": nonzero_node_heads,
                        }
                    ],
                ),
                "no_results",
                True,
            )
        return (None, "results", False)

    if total_nonzero_heads > 0:
        return (
            ValidationCheckItem(
                code=CheckCode.RESULTS_IN_NO_RESULTS_MODE,
                severity="warning",
                count=1,
                message=(
                    f"Запрошен режим mode='no_results', однако в выгрузке обнаружено "
                    f"{total_nonzero_heads} ненулевых значений рассчитанных напоров."
                ),
                developer_hint=(
                    "Если требуется анализ результатов гидравлического расчёта, используйте mode='results'."
                ),
                examples=[
                    {
                        "requested_mode": "no_results",
                        "calculation_status": calc_status,
                        "nonzero_timeseries_heads": nonzero_ts_heads + nonzero_wide_heads,
                        "nonzero_node_calculated_heads": nonzero_node_heads,
                    }
                ],
            ),
            "no_results",
            False,
        )

    return (None, "no_results", False)
