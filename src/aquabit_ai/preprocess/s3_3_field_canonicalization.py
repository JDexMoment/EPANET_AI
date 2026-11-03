"""Подэтап 3.3 — Канонизация имён полей строго по словарю field_aliases.yaml (§4, п. 3.3)."""

from __future__ import annotations

import pandas as pd

from aquabit_ai.config.csv_contracts import (
    AliasRegistry,
    NonCanonicalColumnRule,
    get_contract_for_path,
)
from aquabit_ai.preprocess.errors import PreprocessingFatalError
from aquabit_ai.preprocess.log import PreprocessingLogger


STAGE_NAME = "3.3_field_canonicalization"


def canonicalize_field_names(
    tables: dict[str, pd.DataFrame],
    registry: AliasRegistry,
    logger: PreprocessingLogger,
    *,
    legacy_compat: bool = False,
) -> tuple[dict[str, pd.DataFrame], dict[tuple[str, str], NonCanonicalColumnRule]]:
    """Приводит имена колонок к snake_case с суффиксом единицы без эвристик (§4, п. 3.3).

    Возвращает:
      - словарь таблиц с канонизированными именами колонок;
      - словарь отложенных правил перевода единиц {(file, intermediate_col): NonCanonicalColumnRule} для п. 3.4.
    """
    out_tables: dict[str, pd.DataFrame] = {}
    pending_unit_rules: dict[tuple[str, str], NonCanonicalColumnRule] = {}

    for rel_path, df in sorted(tables.items()):
        contract = get_contract_for_path(rel_path)
        resolved = registry.resolve_table_headers(list(df.columns), contract)

        rename_map: dict[str, str] = {}
        seen_targets: dict[str, str] = {}

        for raw_col in df.columns:
            non_can_rule = registry.get_non_canonical_unit_rule(raw_col)
            if non_can_rule is not None:
                # Промежуточное snake_case имя с фактической входной единицей (например, flow_l_s)
                base_prefix = non_can_rule.target_canonical.rsplit(
                    f"_{non_can_rule.conversion.to_unit}", 1
                )[0]
                intermediate_col = f"{base_prefix}_{non_can_rule.conversion.from_unit}"
                target_name = intermediate_col
                pending_unit_rules[(rel_path, intermediate_col)] = non_can_rule
            else:
                can_col = resolved.get(raw_col)
                if can_col is None:
                    # Для вспомогательных таблиц charts/* и reports/* сохраняем если уже snake_case,
                    # а для контрактных таблиц неразрешённая колонка логируется предупреждением
                    target_name = raw_col.strip()
                    logger.record(
                        stage=STAGE_NAME,
                        operation="unmapped_column_preserved",
                        file=rel_path,
                        field=raw_col,
                        before=raw_col,
                        after=target_name,
                        affected_rows=len(df),
                        severity="warning",
                    )
                    rename_map[raw_col] = target_name
                    continue
                target_name = can_col

            if target_name in seen_targets:
                raise PreprocessingFatalError(
                    "SCHEMA_MISMATCH",
                    f"Две колонки ('{seen_targets[target_name]}' и '{raw_col}') в '{rel_path}' "
                    f"отображаются в одно каноническое поле '{target_name}'",
                    file=rel_path,
                    field=target_name,
                )
            seen_targets[target_name] = raw_col
            rename_map[raw_col] = target_name

            if raw_col != target_name:
                logger.record(
                    stage=STAGE_NAME,
                    operation="rename_column_to_canonical",
                    file=rel_path,
                    field=target_name,
                    before=raw_col,
                    after=target_name,
                    affected_rows=len(df),
                    severity="info",
                )

        new_df = df.rename(columns=rename_map)

        # В режиме обратной совместимости со старым однофайловым экспортом AquaBit (ADR-0006):
        # если в таблице объекта есть только 'name' ('Название') без отдельного 'id', создаём 'id' = 'name'
        if (
            legacy_compat
            and contract is not None
            and contract.primary_id_column == "id"
            and "id" not in new_df.columns
            and "name" in new_df.columns
        ):
            id_series = new_df["name"].copy()
            id_series.name = "id"
            new_df.insert(0, "id", id_series)
            logger.record(
                stage=STAGE_NAME,
                operation="derive_id_from_legacy_name_column",
                file=rel_path,
                field="id",
                before="name (Название)",
                after="id",
                affected_rows=len(new_df),
                severity="warning",
                details={"reason": "В легаси-выгрузке AquaBit отсутствует отдельная колонка ID"},
            )

        if contract is not None:
            future_cols = set(new_df.columns) | {
                rule.target_canonical
                for (f, _), rule in pending_unit_rules.items()
                if f == rel_path
            }
            missing = [req for req in contract.required_columns if req not in future_cols]
            if missing:
                raise PreprocessingFatalError(
                    "SCHEMA_MISMATCH",
                    f"После канонизации в '{rel_path}' отсутствуют обязательные поля: {missing}",
                    file=rel_path,
                    examples=[{"missing": missing, "present": list(new_df.columns)}],
                )
            for any_grp in contract.any_of_required_groups:
                if not any(cand in future_cols for cand in any_grp):
                    raise PreprocessingFatalError(
                        "SCHEMA_MISMATCH",
                        f"После канонизации в '{rel_path}' отсутствует хотя бы одно из полей: {list(any_grp)}",
                        file=rel_path,
                        examples=[{"expected_any_of": list(any_grp), "present": list(new_df.columns)}],
                    )

        out_tables[rel_path] = new_df

    return out_tables, pending_unit_rules
