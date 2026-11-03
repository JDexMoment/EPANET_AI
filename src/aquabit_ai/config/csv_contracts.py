"""Декларативные контракты CSV-таблиц AquaBit и загрузчик field_aliases.yaml (§2, §4 п. 2 и 3.2–3.4, ADR-0007)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_ALIASES_PATH = Path(__file__).with_name("field_aliases.yaml")
WIDE_STEP_HEADER_RE = re.compile(r"^R(\d+)$")


def is_wide_step_header(col_name: str) -> bool:
    """Возвращает True, если заголовок имеет вид R0, R1, ..., R1439 (широкая временна́я матрица)."""
    return WIDE_STEP_HEADER_RE.match(col_name.strip()) is not None


@dataclass(frozen=True)
class CanonicalFieldDef:
    """Описание канонического поля из field_aliases.yaml."""

    canonical_name: str
    kind: str
    requires_unit_suffix: bool
    canonical_unit: str | None
    aliases: tuple[str, ...]
    allowed_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnitConversionRule:
    """Линейное правило перевода единиц измерения (§3.4)."""

    name: str
    from_unit: str
    to_unit: str
    multiplier: float


@dataclass(frozen=True)
class NonCanonicalColumnRule:
    """Правило приведения колонки с неканонической единицей к канону."""

    raw_column_name: str
    target_canonical: str
    conversion: UnitConversionRule
    is_hydraulic_quantity: bool


@dataclass(frozen=True)
class TableContract:
    """Контракт одной CSV-таблицы экспорта AquaBit."""

    path_pattern: str
    entity_type: str
    mandatory_always: bool
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...] = ()
    any_of_required_groups: tuple[tuple[str, ...], ...] = ()
    primary_id_column: str | None = "id"
    is_wide_timeseries: bool = False
    wide_metric_canonical: str | None = None
    wide_target_entity_type: str | None = None
    description: str = ""


class AliasRegistry:
    """Реестр алиасов заголовков, единиц измерения и enum-доменов (без эвристик)."""

    def __init__(
        self,
        fields: dict[str, CanonicalFieldDef],
        recognized_unit_suffixes: tuple[str, ...],
        unit_conversions: dict[str, UnitConversionRule] | None = None,
        non_canonical_columns: dict[str, NonCanonicalColumnRule] | None = None,
        table_specific_aliases: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.fields = fields
        self.recognized_unit_suffixes = recognized_unit_suffixes
        self.unit_conversions = unit_conversions or {}
        self.non_canonical_columns = non_canonical_columns or {}
        self.table_specific_aliases = table_specific_aliases or {}
        self._alias_to_canonical: dict[str, list[str]] = {}
        for canonical_name, fdef in fields.items():
            for alias in (canonical_name, *fdef.aliases):
                key = alias.strip()
                bucket = self._alias_to_canonical.setdefault(key, [])
                if canonical_name not in bucket:
                    bucket.append(canonical_name)

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> "AliasRegistry":
        yaml_path = path or DEFAULT_ALIASES_PATH
        raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        suffixes = tuple(str(s) for s in raw.get("recognized_unit_suffixes", []))
        fields: dict[str, CanonicalFieldDef] = {}
        for cname, meta in raw.get("canonical_fields", {}).items():
            fields[cname] = CanonicalFieldDef(
                canonical_name=cname,
                kind=str(meta.get("kind", "str_text")),
                requires_unit_suffix=bool(meta.get("requires_unit_suffix", False)),
                canonical_unit=meta.get("canonical_unit"),
                aliases=tuple(str(a) for a in meta.get("aliases", [])),
                allowed_values=tuple(str(v) for v in meta.get("allowed_values", [])),
            )

        conv_rules: dict[str, UnitConversionRule] = {}
        for rname, rmeta in raw.get("unit_conversions", {}).items():
            conv_rules[rname] = UnitConversionRule(
                name=rname,
                from_unit=str(rmeta["from_unit"]),
                to_unit=str(rmeta["to_unit"]),
                multiplier=float(rmeta["multiplier"]),
            )

        non_can_cols: dict[str, NonCanonicalColumnRule] = {}
        for col_name, cmeta in raw.get("non_canonical_unit_columns", {}).items():
            conv_key = str(cmeta["conversion"])
            non_can_cols[col_name.strip()] = NonCanonicalColumnRule(
                raw_column_name=col_name.strip(),
                target_canonical=str(cmeta["target_canonical"]),
                conversion=conv_rules[conv_key],
                is_hydraulic_quantity=bool(cmeta.get("is_hydraulic_quantity", False)),
            )

        tbl_specific: dict[str, dict[str, str]] = {}
        for tbl_path, mapping in raw.get("table_specific_aliases", {}).items():
            tbl_specific[str(tbl_path).strip()] = {
                str(k).strip(): str(v).strip() for k, v in (mapping or {}).items()
            }

        return cls(
            fields=fields,
            recognized_unit_suffixes=suffixes,
            unit_conversions=conv_rules,
            non_canonical_columns=non_can_cols,
            table_specific_aliases=tbl_specific,
        )

    def resolve_header(
        self,
        raw_header: str,
        preferred_candidates: set[str] | None = None,
    ) -> str | None:
        """Разрешает сырое имя колонки в каноническое только по явному словарю."""
        key = raw_header.strip()
        matches = self._alias_to_canonical.get(key)
        if not matches:
            return None
        if preferred_candidates:
            for m in matches:
                if m in preferred_candidates:
                    return m
        return matches[0]

    def resolve_table_headers(
        self,
        raw_headers: list[str],
        contract: TableContract | None = None,
    ) -> dict[str, str | None]:
        """Возвращает отображение {raw_header: canonical_name | None} для заголовков таблицы."""
        preferred: set[str] | None = None
        table_overrides: dict[str, str] = {}
        if contract is not None:
            preferred = set(contract.required_columns) | set(contract.optional_columns)
            for grp in contract.any_of_required_groups:
                preferred.update(grp)
            table_overrides = self.table_specific_aliases.get(contract.path_pattern, {})

        # Сначала определяем глобальное разрешение для проверки, не занято ли уже целевое поле
        global_resolved = {h: self.resolve_header(h, preferred) for h in raw_headers}
        already_present_targets = {
            can
            for h, can in global_resolved.items()
            if can is not None and h.strip() not in table_overrides
        }

        final_resolved: dict[str, str | None] = {}
        for h in raw_headers:
            cleaned = h.strip()
            if cleaned in table_overrides:
                override_target = table_overrides[cleaned]
                # Если целевое поле (например, node_id в demands.csv) уже явно задано другой колонкой,
                # сохраняем стандартное разрешение ('ID' -> 'id'), иначе применяем табличный оверрайд
                if override_target not in already_present_targets:
                    final_resolved[h] = override_target
                    continue
            final_resolved[h] = global_resolved[h]
        return final_resolved

    def has_canonical_unit_suffix(self, raw_header: str) -> bool:
        """Проверяет наличие явного канонического суффикса единицы (_m, _m3_h и т.д.)."""
        cleaned = raw_header.strip()
        return any(cleaned.endswith(sfx) for sfx in self.recognized_unit_suffixes)

    def get_non_canonical_unit_rule(self, raw_header: str) -> NonCanonicalColumnRule | None:
        """Возвращает правило конвертации единицы, если сырая колонка в неканонических единицах."""
        return self.non_canonical_columns.get(raw_header.strip())


# Обязательные файлы, которые обязаны присутствовать в каждом ZIP (§2, §4 Этап 1.3)
ALWAYS_MANDATORY_FILES: tuple[str, ...] = (
    "manifest.json",
    "nodes.csv",
    "pipes.csv",
    "sources.csv",
)

# Декларативные контракты таблиц §2 + реальных колонок AquaBit + широких матриц папок городов (ADR-0007)
TABLE_CONTRACTS: dict[str, TableContract] = {
    "nodes.csv": TableContract(
        path_pattern="nodes.csv",
        entity_type="node",
        mandatory_always=True,
        required_columns=("id", "elevation_m"),
        optional_columns=(
            "name",
            "required_pressure_m",
            "calculated_head_m",
            "calculated_demand_m3_h",
            "pressure_m",
            "pressure_bar",
            "base_demand_m3_h",
            "curve_id",
            "is_active",
        ),
        primary_id_column="id",
        description="Расчётные узлы сети",
    ),
    "pipes.csv": TableContract(
        path_pattern="pipes.csv",
        entity_type="pipe",
        mandatory_always=True,
        required_columns=("id", "start_node_id", "end_node_id", "length_m", "diameter_mm"),
        optional_columns=(
            "name",
            "roughness",
            "minor_loss_coeff",
            "flow_m3_h",
            "velocity_m_s",
            "state",
            "is_active",
        ),
        primary_id_column="id",
        description="Трубопроводные участки",
    ),
    "sources.csv": TableContract(
        path_pattern="sources.csv",
        entity_type="source",
        mandatory_always=True,
        required_columns=("id", "head_m"),
        optional_columns=("name", "node_id", "elevation_m", "flow_m3_h", "curve_id"),
        primary_id_column="id",
        description="Источники водоснабжения (граничные напоры/подачи)",
    ),
    "reservoirs.csv": TableContract(
        path_pattern="reservoirs.csv",
        entity_type="reservoir",
        mandatory_always=False,
        required_columns=("id", "elevation_m", "level_m"),
        optional_columns=("name", "node_id", "min_level_m", "max_level_m", "diameter_mm"),
        primary_id_column="id",
        description="Резервуары чистой воды / водонапорные башни",
    ),
    "pumps.csv": TableContract(
        path_pattern="pumps.csv",
        entity_type="pump",
        mandatory_always=False,
        required_columns=("id", "start_node_id", "end_node_id"),
        optional_columns=("name", "curve_id", "state", "flow_m3_h", "head_m", "is_active"),
        primary_id_column="id",
        description="Насосные агрегаты",
    ),
    "pump_curves.csv": TableContract(
        path_pattern="pump_curves.csv",
        entity_type="pump_curve",
        mandatory_always=False,
        required_columns=("flow_m3_h", "head_m"),
        optional_columns=("pump_id", "curve_id", "step_index"),
        any_of_required_groups=(("pump_id", "curve_id"),),
        primary_id_column=None,
        description="Паспортные Q-H характеристики насосов (≥3 точки на насос или кривую curve_id)",
    ),
    "valves.csv": TableContract(
        path_pattern="valves.csv",
        entity_type="valve",
        mandatory_always=False,
        required_columns=("id", "start_node_id", "end_node_id"),
        optional_columns=("name", "diameter_mm", "valve_type", "setting", "state", "flow_m3_h"),
        primary_id_column="id",
        description="Запорно-регулирующая арматура / клапаны",
    ),
    "demands.csv": TableContract(
        path_pattern="demands.csv",
        entity_type="demand",
        mandatory_always=False,
        required_columns=("node_id", "base_demand_m3_h"),
        optional_columns=("id", "curve_id", "name"),
        primary_id_column=None,
        description="Базовые узловые потребности (Потребители Узел)",
    ),
    "irregularity_curves.csv": TableContract(
        path_pattern="irregularity_curves.csv",
        entity_type="irregularity_curve",
        mandatory_always=False,
        required_columns=("curve_id", "multiplier"),
        optional_columns=("step_index", "time_iso8601", "name"),
        primary_id_column=None,
        description="Суточные кривые неравномерности водопотребления (График потребления)",
    ),
    "timeseries/node_pressure.csv": TableContract(
        path_pattern="timeseries/node_pressure.csv",
        entity_type="timeseries_node_pressure",
        mandatory_always=False,
        required_columns=("id", "time_iso8601", "head_m"),
        optional_columns=("pressure_m", "pressure_bar"),
        primary_id_column=None,
        description="Временной ряд напоров в узлах (длинный формат)",
    ),
    "timeseries/node_demand.csv": TableContract(
        path_pattern="timeseries/node_demand.csv",
        entity_type="timeseries_node_demand",
        mandatory_always=False,
        required_columns=("id", "time_iso8601", "demand_m3_h"),
        optional_columns=(),
        primary_id_column=None,
        description="Временной ряд отборов в узлах (длинный формат)",
    ),
    "timeseries/pipe_flow.csv": TableContract(
        path_pattern="timeseries/pipe_flow.csv",
        entity_type="timeseries_pipe_flow",
        mandatory_always=False,
        required_columns=("id", "time_iso8601", "flow_m3_h"),
        optional_columns=(),
        primary_id_column=None,
        description="Временной ряд расходов по трубам (длинный формат)",
    ),
    "timeseries/pipe_velocity.csv": TableContract(
        path_pattern="timeseries/pipe_velocity.csv",
        entity_type="timeseries_pipe_velocity",
        mandatory_always=False,
        required_columns=("id", "time_iso8601", "velocity_m_s"),
        optional_columns=(),
        primary_id_column=None,
        description="Временной ряд скоростей в трубах (длинный формат)",
    ),
    "timeseries/pump_state.csv": TableContract(
        path_pattern="timeseries/pump_state.csv",
        entity_type="timeseries_pump_state",
        mandatory_always=False,
        required_columns=("id", "time_iso8601", "flow_m3_h", "head_m", "state"),
        optional_columns=(),
        primary_id_column=None,
        description="Временной ряд рабочих точек и состояний насосов (длинный формат)",
    ),
    "timeseries/reservoir_level.csv": TableContract(
        path_pattern="timeseries/reservoir_level.csv",
        entity_type="timeseries_reservoir_level",
        mandatory_always=False,
        required_columns=("id", "time_iso8601", "level_m"),
        optional_columns=(),
        primary_id_column=None,
        description="Временной ряд уровней воды в резервуарах (длинный формат)",
    ),
    # Контракты широких временны́х матриц ID,R0..R{T-1} для папок городов (ADR-0007)
    "wide/node_head.csv": TableContract(
        path_pattern="wide/node_head.csv",
        entity_type="wide_node_head",
        mandatory_always=False,
        required_columns=("id",),
        primary_id_column="id",
        is_wide_timeseries=True,
        wide_metric_canonical="head_m",
        wide_target_entity_type="node",
        description="Широкая матрица напоров в узлах (Напор Узел.csv: ID,R0..R1439)",
    ),
    "wide/node_demand.csv": TableContract(
        path_pattern="wide/node_demand.csv",
        entity_type="wide_node_demand",
        mandatory_always=False,
        required_columns=("id",),
        primary_id_column="id",
        is_wide_timeseries=True,
        wide_metric_canonical="demand_m3_h",
        wide_target_entity_type="node",
        description="Широкая матрица фактического отбора в узлах (Потребление Узел.csv: ID,R0..R1439)",
    ),
    "wide/pipe_flow.csv": TableContract(
        path_pattern="wide/pipe_flow.csv",
        entity_type="wide_pipe_flow",
        mandatory_always=False,
        required_columns=("id",),
        primary_id_column="id",
        is_wide_timeseries=True,
        wide_metric_canonical="flow_m3_h",
        wide_target_entity_type="pipe",
        description="Широкая матрица потоков в трубах (Поток Труба.csv: ID,R0..R1439)",
    ),
    "wide/valve_flow.csv": TableContract(
        path_pattern="wide/valve_flow.csv",
        entity_type="wide_valve_flow",
        mandatory_always=False,
        required_columns=("id",),
        primary_id_column="id",
        is_wide_timeseries=True,
        wide_metric_canonical="flow_m3_h",
        wide_target_entity_type="valve",
        description="Широкая матрица потоков через клапаны (Поток Клапан.csv: ID,R0..R1439)",
    ),
    "wide/pump_flow.csv": TableContract(
        path_pattern="wide/pump_flow.csv",
        entity_type="wide_pump_flow",
        mandatory_always=False,
        required_columns=("id",),
        primary_id_column="id",
        is_wide_timeseries=True,
        wide_metric_canonical="flow_m3_h",
        wide_target_entity_type="pump",
        description="Широкая матрица подачи насосов (Поток Насос.csv: ID,R0..R1439)",
    ),
    "wide/pipe_velocity.csv": TableContract(
        path_pattern="wide/pipe_velocity.csv",
        entity_type="wide_pipe_velocity",
        mandatory_always=False,
        required_columns=("id",),
        primary_id_column="id",
        is_wide_timeseries=True,
        wide_metric_canonical="velocity_m_s",
        wide_target_entity_type="pipe",
        description="Широкая матрица скоростей в трубах (Скорость Труба.csv: ID,R0..R1439)",
    ),
    "wide/reservoir_level.csv": TableContract(
        path_pattern="wide/reservoir_level.csv",
        entity_type="wide_reservoir_level",
        mandatory_always=False,
        required_columns=("id",),
        primary_id_column="id",
        is_wide_timeseries=True,
        wide_metric_canonical="level_m",
        wide_target_entity_type="reservoir",
        description="Широкая матрица уровней в резервуарах (Уровень Резервуар.csv: ID,R0..R1439)",
    ),
    "wide/pump_head.csv": TableContract(
        path_pattern="wide/pump_head.csv",
        entity_type="wide_pump_head",
        mandatory_always=False,
        required_columns=("id",),
        primary_id_column="id",
        is_wide_timeseries=True,
        wide_metric_canonical="head_m",
        wide_target_entity_type="pump",
        description="Широкая матрица напоров насосов (Напор Насос.csv: ID,R0..R1439)",
    ),
}


def get_contract_for_path(relative_path: str) -> TableContract | None:
    """Возвращает контракт для относительного пути CSV (если таблица стандартизирована)."""
    normalized = relative_path.replace("\\", "/").lstrip("./")
    return TABLE_CONTRACTS.get(normalized)
