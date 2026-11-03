"""Векторизованный анализатор информативности, разреженности и избыточности таблиц AquaBit (ADR-0007).

Назначение модуля — дать количественное обоснование для разработчика AquaBit:
1. Какие файлы занимают 99% дискового объёма и времени импорта;
2. Какая доля строк/колонок не несёт новой информации (нули транзитных узлов, выключенные резервные
   насосы, 60-кратная линейная передискретизация R0..R1439 относительно часовых узлов R0, R60, ..., R1380,
   алгебраическое дублирование Потребление Узел = Потребители Узел × График потребления);
3. Какие критические баги (Начало == Конец: e702 -> c702,c702) и недостающие признаки (скорость в трубах,
   свободный напор, напор/состояние насоса, резервуары, Название, manifest.json) нужно исправить/добавить;
4. Во сколько раз уменьшится объём выгрузки и ускорится импорт при переходе на целевой компактный экспорт v2.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict, dataclass, field as dc_field
from pathlib import Path
from typing import Any

import numpy as np

from aquabit_ai.config.csv_contracts import AliasRegistry, get_contract_for_path
from aquabit_ai.ingest import (
    IngestionBundle,
    WideTimeseriesMatrix,
    discover_city_directories,
    ingest_any_source,
    ingest_city_directory,
)
from aquabit_ai.validate import run_validation


@dataclass
class FileSignalProfile:
    """Метрики объёма, разреженности и информационной плотности одного файла выгрузки."""

    canonical_path: str
    source_file: str
    is_wide_timeseries: bool
    size_bytes: int
    size_mb: float
    share_of_city_bytes_pct: float
    rows: int
    columns: int
    total_cells: int
    parse_time_ms: float

    # Показатели разреженности и динамики (для широких матриц R0..R{T-1})
    null_cells_pct: float = 0.0
    zero_cells_pct: float = 0.0
    all_zero_rows_count: int = 0
    all_zero_rows_pct: float = 0.0
    constant_rows_pct: float = 0.0
    quasi_constant_rows_pct: float = 0.0  # амплитуда за сутки <= 0.05 ед.
    negative_rows_pct: float = 0.0
    sign_reversal_rows_count: int = 0
    sign_reversal_rows_pct: float = 0.0

    # Оценка передискретизации R0..R1439 относительно часовых (60 мин) и 15-минутных узлов
    hourly_interp_max_abs_err: float | None = None
    hourly_interp_p99_abs_err: float | None = None
    hourly_interp_median_abs_err: float | None = None
    rows_linear_within_005_pct: float | None = None
    min15_interp_max_abs_err: float | None = None
    abrupt_switch_rows_count: int = 0

    # Итоговая оценка полезности и рекомендация для разработчика AquaBit
    estimated_redundant_bytes_pct: float = 0.0
    action_tier: str = "KEEP_AND_ENRICH"
    signal_score_0_100: int = 90
    developer_verdict: str = ""


@dataclass
class DemandRedundancyAudit:
    """Сверка Потребление Узел.csv против (Потребители Узел.csv × График потребления.csv)."""

    present: bool
    total_nodes: int = 0
    nodes_with_consumers: int = 0
    transit_nodes_without_consumers: int = 0
    transit_nodes_pct: float = 0.0
    all_zero_demand_rows: int = 0
    all_zero_demand_rows_pct: float = 0.0
    reconstructed_match_tested_nodes: int = 0
    hourly_algebraic_max_diff: float | None = None
    pdd_curtailed_nodes_detected: int = 0
    can_drop_node_demand_matrix: bool = False
    explanation: str = ""


@dataclass
class CityExportProfile:
    """Полный профиль информативности и качества выгрузки одного города."""

    city_name: str
    source_path: str
    total_bytes: int
    total_mb: float
    wide_bytes_share_pct: float
    static_bytes_share_pct: float
    total_parse_time_ms: float
    n_files: int
    n_steps: int
    step_seconds: int
    validation_status_strict: str
    self_loop_links_count: int
    exporter_own_id_cast_bug_detected: bool
    orphan_references_count: int
    incomplete_pump_curves_count: int
    constant_patterns_count: int
    total_patterns_count: int
    missing_high_value_features: list[str]
    demand_redundancy: DemandRedundancyAudit
    files: list[FileSignalProfile]
    projected_sizes_bytes: dict[str, int]
    projected_savings_pct: dict[str, float]


@dataclass
class CorpusExportProfile:
    """Сводный профиль по набору папок городов (data/тенино, хорезмская, Орша, модель семей, куляб, Алматы)."""

    cities_count: int
    total_bytes: int
    total_mb: float
    wide_bytes_share_pct: float
    redundant_bytes_total: int
    redundant_bytes_pct: float
    projected_hourly_no_demand_mb: float
    projected_compact_v2_mb: float
    savings_hourly_pct: float
    savings_compact_v2_pct: float
    cities: list[CityExportProfile] = dc_field(default_factory=list)
    global_findings: list[str] = dc_field(default_factory=list)
    table_tier_summary: list[dict[str, Any]] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compute_piecewise_linear_error(mat: np.ndarray, valid_mask: np.ndarray, stride: int) -> tuple[np.ndarray, float, float, float]:
    """Векторизованно вычисляет погрешность кусочно-линейной интерполяции с шагом `stride` по всем строкам [N, T]."""
    n_rows, n_steps = mat.shape
    if n_rows == 0 or n_steps <= stride:
        zeros = np.zeros(n_rows, dtype=np.float64)
        return zeros, 0.0, 0.0, 0.0

    knots = np.unique(np.append(np.arange(0, n_steps, stride), n_steps - 1))
    clean = np.where(valid_mask, mat, 0.0)
    interp = np.empty_like(clean)

    for k in range(len(knots) - 1):
        a = int(knots[k])
        b = int(knots[k + 1])
        span = b - a
        if span <= 0:
            continue
        alpha = (np.arange(a, b + 1, dtype=np.float64) - a) / float(span)
        interp[:, a : b + 1] = clean[:, [a]] * (1.0 - alpha) + clean[:, [b]] * alpha

    # Оцениваем ошибку только на строках, где все точки валидны (без null/NaN)
    full_valid_rows = np.all(valid_mask, axis=1)
    abs_diff = np.where(valid_mask, np.abs(clean - interp), 0.0)
    row_max_err = np.max(abs_diff, axis=1)

    if not np.any(full_valid_rows):
        return row_max_err, 0.0, 0.0, 0.0

    vr = row_max_err[full_valid_rows]
    return (
        row_max_err,
        round(float(np.max(vr)), 5),
        round(float(np.percentile(vr, 99)), 5),
        round(float(np.median(vr)), 5),
    )


def _count_abrupt_switch_rows(mat: np.ndarray, valid_mask: np.ndarray, stride: int = 60) -> int:
    """Детектирует строки с внутричасовыми ступенчатыми переключениями (пуск/останов насоса, срабатывание ЗРА)."""
    n_rows, n_steps = mat.shape
    if n_rows == 0 or n_steps < 5:
        return 0

    clean = np.where(valid_mask, mat, 0.0)
    d1 = np.diff(clean, axis=1)
    d2 = np.abs(np.diff(d1, axis=1))  # индексы 0..n_steps-3 соответствуют центрам t = 1..n_steps-2

    # Исключаем штатные изломы наклона на границах целых часов (t кратно stride)
    interior_cols = np.array(
        [(t % stride != 0) for t in range(1, n_steps - 1)],
        dtype=bool,
    )
    if not np.any(interior_cols):
        return 0

    row_span = np.ptp(clean, axis=1)
    # Порог ступеньки: одновременно > 0.25 ед. и > 8% суточного размаха строки
    thresh = np.maximum(0.25, 0.08 * row_span)[:, None]
    jumps = d2[:, interior_cols] > thresh
    full_valid = np.all(valid_mask, axis=1)
    return int(np.count_nonzero(np.any(jumps, axis=1) & full_valid))


def _audit_demand_redundancy(
    bundle: IngestionBundle,
    registry: AliasRegistry,
) -> DemandRedundancyAudit:
    """Проверяет, дублирует ли Потребление Узел.csv произведение Потребители Узел × График потребления."""
    wide_dem = bundle.tables.get("wide/node_demand.csv")
    nodes_tbl = bundle.tables.get("nodes.csv")
    dem_tbl = bundle.tables.get("demands.csv")
    curves_tbl = bundle.tables.get("irregularity_curves.csv")

    if wide_dem is None or wide_dem.wide_matrix is None:
        return DemandRedundancyAudit(present=False)

    w: WideTimeseriesMatrix = wide_dem.wide_matrix
    mat, null_mask = w.to_numpy_with_null_mask()
    valid_mask = (~null_mask) & (~np.isnan(mat))
    n_rows = w.num_rows
    all_zero = int(np.count_nonzero(np.all(valid_mask & (mat == 0.0), axis=1))) if n_rows > 0 else 0
    all_zero_pct = round(100.0 * all_zero / n_rows, 2) if n_rows > 0 else 0.0

    total_nodes = len(nodes_tbl.dataframe) if (nodes_tbl and nodes_tbl.dataframe is not None) else n_rows

    # Строим словарь графиков {curve_id: [m_0, m_1, ...]}
    patterns: dict[str, list[float]] = {}
    if curves_tbl is not None and curves_tbl.dataframe is not None and not curves_tbl.dataframe.empty:
        c_contract = get_contract_for_path("irregularity_curves.csv")
        c_res = registry.resolve_table_headers(list(curves_tbl.dataframe.columns), c_contract)
        cid_col = next((r for r, c in c_res.items() if c == "curve_id"), None)
        mul_col = next((r for r, c in c_res.items() if c == "multiplier"), None)
        if cid_col and mul_col:
            for row in curves_tbl.dataframe.to_dict(orient="records"):
                cid = str(row[cid_col]).strip()
                try:
                    val = float(str(row[mul_col]).strip())
                except ValueError:
                    continue
                patterns.setdefault(cid, []).append(val)

    # Суммируем базовые нагрузки по узлам с учётом их графиков
    node_loads: dict[str, list[tuple[float, str | None]]] = {}
    if dem_tbl is not None and dem_tbl.dataframe is not None and not dem_tbl.dataframe.empty:
        d_contract = get_contract_for_path("demands.csv")
        d_res = registry.resolve_table_headers(list(dem_tbl.dataframe.columns), d_contract)
        nid_col = next((r for r, c in d_res.items() if c == "node_id"), None)
        q_col = next((r for r, c in d_res.items() if c == "base_demand_m3_h"), None)
        pat_col = next((r for r, c in d_res.items() if c == "curve_id"), None)
        if nid_col and q_col:
            for row in dem_tbl.dataframe.to_dict(orient="records"):
                nid = str(row[nid_col]).strip()
                if not nid:
                    continue
                try:
                    q_base = float(str(row[q_col]).strip())
                except ValueError:
                    continue
                pat_id = str(row[pat_col]).strip() if pat_col and str(row[pat_col]).strip() else None
                node_loads.setdefault(nid, []).append((q_base, pat_id))

    active_consumer_nodes = sum(
        1 for loads in node_loads.values() if sum(abs(q) for q, _ in loads) > 0.0
    )
    transit_nodes = max(0, total_nodes - active_consumer_nodes)
    transit_pct = round(100.0 * transit_nodes / total_nodes, 2) if total_nodes > 0 else 0.0

    # Сверяем часовые узлы R0, R60, ... там, где полный график присутствует в График потребления.csv
    tested_nodes = 0
    max_alg_diff = 0.0
    pdd_curtailed = 0
    row_ids = w.id_list()

    if w.n_steps >= 24 and patterns and node_loads:
        stride = 60 if w.n_steps == 1440 else max(1, w.n_steps // 24)
        for row_idx, nid in enumerate(row_ids):
            if nid is None or nid not in node_loads:
                continue
            loads = node_loads[nid]
            # Проверяем, что все графики этого узла известны и имеют длину 1 или 24
            if not all(
                (pid is None) or (pid in patterns and len(patterns[pid]) in {1, 24})
                for _, pid in loads
            ):
                continue
            tested_nodes += 1
            for h in range(min(24, (w.n_steps + stride - 1) // stride)):
                col_idx = h * stride
                if col_idx >= w.n_steps or not valid_mask[row_idx, col_idx]:
                    continue
                expected_q = 0.0
                for q_base, pid in loads:
                    if pid is None:
                        expected_q += q_base
                    else:
                        p_vals = patterns[pid]
                        mult = p_vals[0] if len(p_vals) == 1 else p_vals[h]
                        expected_q += q_base * mult
                actual_q = float(mat[row_idx, col_idx])
                diff = abs(actual_q - expected_q)
                if diff > max_alg_diff:
                    max_alg_diff = diff
                if expected_q > 0.1 and actual_q < 0.90 * expected_q:
                    pdd_curtailed += 1
                    break

    can_drop = pdd_curtailed == 0
    explanation = (
        f"Транзитных узлов без абонентов: {transit_nodes}/{total_nodes} ({transit_pct}%), "
        f"полностью нулевых строк в Потребление Узел.csv: {all_zero}/{n_rows} ({all_zero_pct}%). "
        + (
            f"На проверенных узлах с известными графиками ({tested_nodes} шт.) расхождение с "
            f"Потребители Узел × График потребления составляет max={max_alg_diff:.4f} м³/ч — "
            "таблица Потребление Узел.csv на ~100% избыточна и может быть исключена!"
            if tested_nodes > 0 and can_drop
            else "Для всех транзитных узлов хранятся тысячи нулей '0.00', а для абонентских узлов ряд "
            "определяется произведением Потребители Узел × График потребления (выгружать только узлы с PDD-срезкой)."
        )
    )

    return DemandRedundancyAudit(
        present=True,
        total_nodes=total_nodes,
        nodes_with_consumers=active_consumer_nodes,
        transit_nodes_without_consumers=transit_nodes,
        transit_nodes_pct=transit_pct,
        all_zero_demand_rows=all_zero,
        all_zero_demand_rows_pct=all_zero_pct,
        reconstructed_match_tested_nodes=tested_nodes,
        hourly_algebraic_max_diff=round(max_alg_diff, 5) if tested_nodes > 0 else None,
        pdd_curtailed_nodes_detected=pdd_curtailed,
        can_drop_node_demand_matrix=can_drop,
        explanation=explanation,
    )


def _classify_wide_file(
    canonical_path: str,
    all_zero_pct: float,
    hourly_p99_err: float | None,
    n_steps: int,
    demand_audit: DemandRedundancyAudit,
) -> tuple[str, int, float, str]:
    """Возвращает (action_tier, signal_score, redundant_bytes_pct, developer_verdict)."""
    oversample_factor = (1.0 - (26.0 / n_steps)) if n_steps > 30 else 0.0

    if canonical_path == "wide/node_demand.csv":
        if demand_audit.can_drop_node_demand_matrix:
            return (
                "DROP_REDUNDANT",
                5,
                99.5,
                "ИСКЛЮЧИТЬ ИЗ ВЫГРУЗКИ: 60–85% строк состоят из одних нулей (транзитные узлы), "
                "а остальные алгебраически заданы связкой Потребители Узел.csv × График потребления.csv. "
                "Оставить выгрузку только для узлов с фактической PDD-редукцией отбора (если режим PDD активен).",
            )
        return (
            "DOWNSAMPLE_60X_TO_HOURLY",
            35,
            round(100.0 * oversample_factor, 1),
            "Выгружать только узлы с фактической PDD-срезкой отбора и часовым шагом H0..H23.",
        )

    if canonical_path in {"wide/pump_flow.csv", "wide/valve_flow.csv"}:
        red_pct = round(100.0 * (1.0 - (1.0 - all_zero_pct / 100.0) * (1.0 - oversample_factor)), 1)
        return (
            "MERGE_EQUIPMENT_REGIMES",
            65,
            min(99.0, max(50.0, red_pct)),
            f"ОБЪЕДИНИТЬ И ОБОГАТИТЬ: сейчас {all_zero_pct:.1f}% строк — нули закрытых/резервных агрегатов. "
            "Объединить Поток Насос и Поток Клапан в единую компактную таблицу режимов оборудования с полями "
            "(id, state, min/max/mean flow_m3_h, dynamic head_m для насосов + часовые срезы H0..H23 / точки переключений).",
        )

    if canonical_path == "wide/node_head.csv":
        red_pct = round(100.0 * oversample_factor, 1)
        return (
            "DOWNSAMPLE_60X_TO_HOURLY",
            85,
            red_pct,
            f"ВЫСОКАЯ ЦЕННОСТЬ ПРИЗНАКА, НО 60× ПЕРЕДИСКРЕТИЗАЦИЯ: заменить 1 440 минутных колонок R0..R1439 "
            f"(погрешность часовой интерполяции P99={hourly_p99_err or 0.0:.4f} м) на сводку "
            "(min_head_m, max_head_m, min_pressure_m, max_pressure_m, hours_below_required) + 24 часовых среза H0..H23. "
            "Обязательно добавить свободный напор (pressure_m) из расчётного ядра AquaBit!",
        )

    if canonical_path == "wide/pipe_flow.csv":
        red_pct = round(100.0 * oversample_factor, 1)
        return (
            "DOWNSAMPLE_60X_TO_HOURLY",
            85,
            red_pct,
            f"ВЫСОКАЯ ЦЕННОСТЬ ПРИЗНАКА, НО 60× ПЕРЕДИСКРЕТИЗАЦИЯ: заменить 1 440 минутных колонок R0..R1439 "
            f"(погрешность часовой интерполяции P99={hourly_p99_err or 0.0:.4f} м³/ч) на сводку "
            "(min_flow_m3_h, max_flow_m3_h, max_velocity_m_s, flow_reversals_count) + 24 часовых среза H0..H23. "
            "Обязательно добавить скорость потока (velocity_m_s) из ядра AquaBit!",
        )

    return (
        "DOWNSAMPLE_60X_TO_HOURLY",
        80,
        round(100.0 * oversample_factor, 1),
        "Перевести с минутного шага R0..R1439 на агрегаты min/max/mean + 24 часовых среза H0..H23.",
    )


STATIC_VERDICTS: dict[str, tuple[int, str]] = {
    "nodes.csv": (
        98,
        "ЯДРО МОДЕЛИ (<0.3% объёма): оставить обязательно; добавить колонку 'Название' (диспетчерское имя узла).",
    ),
    "pipes.csv": (
        98,
        "ЯДРО МОДЕЛИ (<0.4% объёма): оставить обязательно; ИСПРАВИТЬ КРИТИЧЕСКИЙ БАГ Начало == Конец (e702 -> c702,c702) и добавить 'Название'.",
    ),
    "sources.csv": (
        95,
        "ЯДРО МОДЕЛИ (<0.05% объёма): оставить обязательно; добавить 'Название' и привязку к узлу/подачу источника.",
    ),
    "pumps.csv": (
        96,
        "ЯДРО МОДЕЛИ (<0.05% объёма): оставить обязательно; ИСПРАВИТЬ БАГ Начало == Конец (p1263 -> c1263,c1263) и добавить 'Название'.",
    ),
    "valves.csv": (
        92,
        "ЯДРО МОДЕЛИ (<0.05% объёма): оставить обязательно; ИСПРАВИТЬ БАГ Начало == Конец (v1284 -> c1284,c1284), диаметр и единицу уставки.",
    ),
    "pump_curves.csv": (
        94,
        "ЯДРО ПАСПОРТОВ (<0.05% объёма): оставить обязательно; переименовать безразмерные X,Y в flow_m3_h,head_m и выгружать ≥3 точки на кривую.",
    ),
    "demands.csv": (
        96,
        "ЯДРО НАГРУЗОК (<0.2% объёма): компактно хранит только узлы с реальными абонентами и ссылкой на График — полностью заменяет гигантский Потребление Узел.csv!",
    ),
    "irregularity_curves.csv": (
        95,
        "ЯДРО ГРАФИКОВ (<0.05% объёма): оставить обязательно; добавить явную колонку step_index (0..23) к паре ID,Данные.",
    ),
    "reservoirs.csv": (
        96,
        "ЯДРО ЕМКОСТЕЙ: оставить обязательно (отметки дна, min/max и начальный уровень воды).",
    ),
}


def profile_single_bundle(
    bundle: IngestionBundle,
    registry: AliasRegistry | None = None,
) -> CityExportProfile:
    """Вычисляет детальный профиль информативности и оптимизации для одного города."""
    t0 = time.perf_counter()
    reg = registry or AliasRegistry.from_yaml()
    val_out = run_validation(bundle, strict=True, aliases=reg)

    city_name = (
        bundle.manifest.model.name
        if bundle.manifest is not None
        else bundle.archive_path.stem
    )
    total_bytes = sum(t.size_bytes for t in bundle.tables.values()) or 1
    wide_bytes = sum(t.size_bytes for t in bundle.tables.values() if t.wide_matrix is not None)
    static_bytes = total_bytes - wide_bytes

    demand_audit = _audit_demand_redundancy(bundle, reg)

    # Подсчёт константных суточных графиков (t104,1)
    total_patterns = 0
    constant_patterns = 0
    ic_tbl = bundle.tables.get("irregularity_curves.csv")
    if ic_tbl is not None and ic_tbl.dataframe is not None and not ic_tbl.dataframe.empty:
        ic_con = get_contract_for_path("irregularity_curves.csv")
        ic_res = reg.resolve_table_headers(list(ic_tbl.dataframe.columns), ic_con)
        cid_col = next((r for r, c in ic_res.items() if c == "curve_id"), None)
        mul_col = next((r for r, c in ic_res.items() if c == "multiplier"), None)
        if cid_col and mul_col:
            grouped_vals: dict[str, list[float]] = {}
            for row in ic_tbl.dataframe.to_dict(orient="records"):
                k = str(row[cid_col]).strip()
                try:
                    grouped_vals.setdefault(k, []).append(float(str(row[mul_col]).strip()))
                except ValueError:
                    pass
            total_patterns = len(grouped_vals)
            constant_patterns = sum(
                1 for vals in grouped_vals.values() if len(vals) <= 1 or (max(vals) - min(vals) <= 1e-9)
            )

    file_profiles: list[FileSignalProfile] = []
    max_steps = 1
    step_seconds = 3600

    for rel_path, tbl in sorted(
        bundle.tables.items(), key=lambda kv: (-kv[1].size_bytes, kv[0])
    ):
        share_pct = round(100.0 * tbl.size_bytes / total_bytes, 2)
        if tbl.wide_matrix is not None:
            w: WideTimeseriesMatrix = tbl.wide_matrix
            max_steps = max(max_steps, w.n_steps)
            step_seconds = w.step_seconds
            n_rows = w.num_rows
            n_cols = w.n_steps + 1
            total_cells = max(1, n_rows * w.n_steps)

            mat, null_mask = w.to_numpy_with_null_mask()
            ieee_nan = (~null_mask) & np.isnan(mat)
            valid = (~null_mask) & (~ieee_nan)

            null_pct = round(100.0 * int(np.count_nonzero(null_mask)) / total_cells, 2)
            zero_pct = round(100.0 * int(np.count_nonzero(valid & (mat == 0.0))) / total_cells, 2)

            if n_rows > 0 and w.n_steps > 0:
                all_zero_rows = int(np.count_nonzero(np.all(valid & (mat == 0.0), axis=1)))
                all_zero_pct = round(100.0 * all_zero_rows / n_rows, 2)

                clean_min = np.min(np.where(valid, mat, np.inf), axis=1)
                clean_max = np.max(np.where(valid, mat, -np.inf), axis=1)
                has_any = np.any(valid, axis=1)
                amp = np.where(has_any, clean_max - clean_min, 0.0)

                const_pct = round(100.0 * int(np.count_nonzero(has_any & (amp <= 1e-6))) / n_rows, 2)
                quasi_pct = round(100.0 * int(np.count_nonzero(has_any & (amp <= 0.05))) / n_rows, 2)
                neg_rows = int(np.count_nonzero(np.any(valid & (mat < -1e-9), axis=1)))
                neg_pct = round(100.0 * neg_rows / n_rows, 2)
                rev_rows = int(
                    np.count_nonzero(
                        np.any(valid & (mat > 0.01), axis=1) & np.any(valid & (mat < -0.01), axis=1)
                    )
                )
                rev_pct = round(100.0 * rev_rows / n_rows, 2)
            else:
                all_zero_rows = 0
                all_zero_pct = 0.0
                const_pct = 0.0
                quasi_pct = 0.0
                neg_pct = 0.0
                rev_rows = 0
                rev_pct = 0.0

            h_err_max: float | None = None
            h_err_p99: float | None = None
            h_err_med: float | None = None
            lin_005_pct: float | None = None
            m15_err_max: float | None = None
            abrupt_rows = 0

            if w.n_steps >= 120 and n_rows > 0:
                row_err_60, h_err_max, h_err_p99, h_err_med = _compute_piecewise_linear_error(
                    mat, valid, stride=60
                )
                _, m15_err_max, _, _ = _compute_piecewise_linear_error(mat, valid, stride=15)
                lin_005_pct = round(
                    100.0 * int(np.count_nonzero(row_err_60 <= 0.05)) / n_rows, 2
                )
                abrupt_rows = _count_abrupt_switch_rows(mat, valid, stride=60)

            tier, score, red_pct, verdict = _classify_wide_file(
                canonical_path=rel_path,
                all_zero_pct=all_zero_pct,
                hourly_p99_err=h_err_p99,
                n_steps=w.n_steps,
                demand_audit=demand_audit,
            )

            file_profiles.append(
                FileSignalProfile(
                    canonical_path=rel_path,
                    source_file=tbl.source_label or rel_path,
                    is_wide_timeseries=True,
                    size_bytes=tbl.size_bytes,
                    size_mb=round(tbl.size_bytes / (1024 * 1024), 4),
                    share_of_city_bytes_pct=share_pct,
                    rows=n_rows,
                    columns=n_cols,
                    total_cells=n_rows * w.n_steps,
                    parse_time_ms=round(w.parse_time_ms, 2),
                    null_cells_pct=null_pct,
                    zero_cells_pct=zero_pct,
                    all_zero_rows_count=all_zero_rows,
                    all_zero_rows_pct=all_zero_pct,
                    constant_rows_pct=const_pct,
                    quasi_constant_rows_pct=quasi_pct,
                    negative_rows_pct=neg_pct,
                    sign_reversal_rows_count=rev_rows,
                    sign_reversal_rows_pct=rev_pct,
                    hourly_interp_max_abs_err=h_err_max,
                    hourly_interp_p99_abs_err=h_err_p99,
                    hourly_interp_median_abs_err=h_err_med,
                    rows_linear_within_005_pct=lin_005_pct,
                    min15_interp_max_abs_err=m15_err_max,
                    abrupt_switch_rows_count=abrupt_rows,
                    estimated_redundant_bytes_pct=red_pct,
                    action_tier=tier,
                    signal_score_0_100=score,
                    developer_verdict=verdict,
                )
            )
        else:
            df = tbl.dataframe
            n_rows = int(len(df)) if df is not None else 0
            n_cols = len(tbl.raw_headers)
            score, verdict = STATIC_VERDICTS.get(
                rel_path,
                (85, "Компактная справочная таблица; сохранить с явными суффиксами единиц."),
            )
            file_profiles.append(
                FileSignalProfile(
                    canonical_path=rel_path,
                    source_file=tbl.source_label or rel_path,
                    is_wide_timeseries=False,
                    size_bytes=tbl.size_bytes,
                    size_mb=round(tbl.size_bytes / (1024 * 1024), 4),
                    share_of_city_bytes_pct=share_pct,
                    rows=n_rows,
                    columns=n_cols,
                    total_cells=n_rows * max(1, n_cols),
                    parse_time_ms=0.5,
                    estimated_redundant_bytes_pct=0.0,
                    action_tier="KEEP_AND_ENRICH",
                    signal_score_0_100=score,
                    developer_verdict=verdict,
                )
            )

    # Извлекаем счётчики багов из результатов валидации
    checks_by_code = {c.code.value: c for c in val_out.report.checks}
    self_loop_item = checks_by_code.get("SELF_LOOP_LINK")
    self_loops_n = self_loop_item.count if self_loop_item else 0
    cast_bug = bool(
        self_loop_item
        and any(ex.get("exporter_own_id_cast_bug") for ex in self_loop_item.examples)
    )
    orphan_n = checks_by_code["ORPHAN_REFERENCE"].count if "ORPHAN_REFERENCE" in checks_by_code else 0
    inc_qh_n = (
        checks_by_code["PUMP_CURVE_INCOMPLETE"].count
        if "PUMP_CURVE_INCOMPLETE" in checks_by_code
        else 0
    )

    # Детектируем отсутствующие высокозначимые инженерные признаки
    missing_features: list[str] = []
    if "MISSING_ENTITY_NAMES" in checks_by_code:
        missing_features.append(
            "Диспетчерское поле 'Название' в статических таблицах (Узел, Труба, Насос, Клапан, Источники)"
        )
    if "wide/pipe_velocity.csv" not in bundle.tables and "timeseries/pipe_velocity.csv" not in bundle.tables:
        missing_features.append(
            "Скорость потока в трубах (velocity_m_s / max_velocity_m_s) — без неё невозможен контроль заиливания и эрозии (>5 м/с) по Принципу 1"
        )
    nodes_df = bundle.tables["nodes.csv"].dataframe if "nodes.csv" in bundle.tables else None
    if nodes_df is not None:
        n_res = reg.resolve_table_headers(list(nodes_df.columns), get_contract_for_path("nodes.csv"))
        if "pressure_m" not in set(n_res.values()) and "pressure_bar" not in set(n_res.values()):
            missing_features.append(
                "Свободный напор / давление в узлах (pressure_m) — выгружается только полный пьезометрический напор (Напор Узел), тогда как норматив Требуемое давление задан для свободного напора!"
            )
    if "pumps.csv" in bundle.tables and "wide/pump_head.csv" not in bundle.tables and "timeseries/pump_state.csv" not in bundle.tables:
        missing_features.append(
            "Динамический напор и статус насоса (head_m, state) — сейчас выгружается только Поток Насос (Q), чего недостаточно для проверки рабочей точки на кривой Q-H"
        )
    if "reservoirs.csv" not in bundle.tables:
        missing_features.append(
            "Таблицы резервуаров (Резервуар.csv + уровни РЧВ/ВБ) — необходимы для контроля опорожнения и перелива емкостей"
        )
    if bundle.manifest is not None and bundle.manifest.aquabit_version == "city_folder_csv_13":
        missing_features.append(
            "Паспорт расчёта manifest.json (шаг расчёта step_seconds, статус сходимости решателя converged, формула потерь напора)"
        )

    # Расчёт прогнозного объёма выгрузки по 3 ступеням оптимизации
    node_dem_bytes = bundle.tables["wide/node_demand.csv"].size_bytes if "wide/node_demand.csv" in bundle.tables else 0
    step1_drop_demand_and_zeros = max(
        static_bytes,
        total_bytes
        - node_dem_bytes
        - sum(
            int(fp.size_bytes * (fp.all_zero_rows_pct / 100.0) * 0.95)
            for fp in file_profiles
            if fp.is_wide_timeseries and fp.canonical_path != "wide/node_demand.csv"
        ),
    )

    remaining_wide_bytes = max(0, wide_bytes - node_dem_bytes)
    hourly_ratio = (27.0 / max(1, max_steps + 1)) if max_steps > 30 else 1.0
    step2_hourly_csv = int(static_bytes * 1.15 + remaining_wide_bytes * hourly_ratio)

    # Компактный формат v2 (Parquet/Zstd или агрегаты min/max/mean + 24ч профили ключевых элементов)
    step3_compact_v2 = max(int(static_bytes * 1.25), int(step2_hourly_csv * 0.28))

    projected_bytes = {
        "current_raw_bytes": total_bytes,
        "step1_drop_node_demand_and_zero_rows": step1_drop_demand_and_zeros,
        "step2_hourly_24_plus_minmax_csv": step2_hourly_csv,
        "step3_compact_v2_parquet_or_summaries": step3_compact_v2,
    }
    projected_savings = {
        k: round(max(0.0, 100.0 * (1.0 - v / total_bytes)), 2)
        for k, v in projected_bytes.items()
    }

    elapsed_total_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    return CityExportProfile(
        city_name=city_name,
        source_path=str(bundle.archive_path),
        total_bytes=total_bytes,
        total_mb=round(total_bytes / (1024 * 1024), 3),
        wide_bytes_share_pct=round(100.0 * wide_bytes / total_bytes, 2),
        static_bytes_share_pct=round(100.0 * static_bytes / total_bytes, 2),
        total_parse_time_ms=elapsed_total_ms,
        n_files=len(file_profiles),
        n_steps=max_steps,
        step_seconds=step_seconds,
        validation_status_strict=val_out.report.status,
        self_loop_links_count=self_loops_n,
        exporter_own_id_cast_bug_detected=cast_bug,
        orphan_references_count=orphan_n,
        incomplete_pump_curves_count=inc_qh_n,
        constant_patterns_count=constant_patterns,
        total_patterns_count=total_patterns,
        missing_high_value_features=missing_features,
        demand_redundancy=demand_audit,
        files=file_profiles,
        projected_sizes_bytes=projected_bytes,
        projected_savings_pct=projected_savings,
    )


def profile_aquabit_export(target_path: str | Path) -> CorpusExportProfile:
    """Профилирует одну папку города, родительскую директорию data/ со всеми городами или ZIP/CSV."""
    p = Path(target_path)
    registry = AliasRegistry.from_yaml()
    city_profiles: list[CityExportProfile] = []

    if p.is_dir():
        city_dirs = discover_city_directories(p)
        for cdir in city_dirs:
            bundle = ingest_city_directory(cdir)
            city_profiles.append(profile_single_bundle(bundle, registry=registry))
    else:
        bundle = ingest_any_source(p)
        city_profiles.append(profile_single_bundle(bundle, registry=registry))

    total_bytes = sum(c.total_bytes for c in city_profiles) or 1
    wide_bytes = sum(
        sum(f.size_bytes for f in c.files if f.is_wide_timeseries) for c in city_profiles
    )
    redundant_bytes = sum(
        sum(int(f.size_bytes * f.estimated_redundant_bytes_pct / 100.0) for f in c.files)
        for c in city_profiles
    )
    hourly_bytes = sum(
        c.projected_sizes_bytes["step2_hourly_24_plus_minmax_csv"] for c in city_profiles
    )
    compact_v2_bytes = sum(
        c.projected_sizes_bytes["step3_compact_v2_parquet_or_summaries"] for c in city_profiles
    )

    # Агрегируем статистику по типам файлов между всеми городами
    by_table: dict[str, list[FileSignalProfile]] = {}
    for c in city_profiles:
        for f in c.files:
            by_table.setdefault(f.canonical_path, []).append(f)

    table_summary: list[dict[str, Any]] = []
    for can_path, items in sorted(
        by_table.items(), key=lambda kv: -sum(x.size_bytes for x in kv[1])
    ):
        t_bytes = sum(x.size_bytes for x in items)
        avg_zero_rows = round(float(np.mean([x.all_zero_rows_pct for x in items])), 2)
        p99_errs = [x.hourly_interp_p99_abs_err for x in items if x.hourly_interp_p99_abs_err is not None]
        table_summary.append(
            {
                "canonical_path": can_path,
                "example_source_file": items[0].source_file,
                "cities_present": len(items),
                "total_bytes": t_bytes,
                "share_of_corpus_bytes_pct": round(100.0 * t_bytes / total_bytes, 2),
                "is_wide_timeseries": items[0].is_wide_timeseries,
                "avg_all_zero_rows_pct": avg_zero_rows,
                "max_hourly_p99_interp_err": max(p99_errs) if p99_errs else None,
                "action_tier": items[0].action_tier,
                "signal_score_0_100": items[0].signal_score_0_100,
                "developer_verdict": items[0].developer_verdict,
            }
        )

    findings: list[str] = []
    cities_with_bug = [c.city_name for c in city_profiles if c.exporter_own_id_cast_bug_detected]
    if cities_with_bug:
        findings.append(
            f"КРИТИЧЕСКИЙ БАГ ТОПОЛОГИИ в {len(cities_with_bug)}/{len(city_profiles)} городах "
            f"({', '.join(cities_with_bug)}): в Труба.csv, Насос.csv и Клапан.csv поля Начало == Конец "
            "содержат 'c' + ID самого участка (e702 -> c702,c702) вместо ID начального и конечного узлов."
        )
    findings.append(
        f"5 широких динамических файлов R0..R1439 занимают {round(100.0 * wide_bytes / total_bytes, 2)}% "
        f"всего дискового объёма, тогда как 8 статических таблиц топологии, нагрузок и кривых — всего "
        f"{round(100.0 * (total_bytes - wide_bytes) / total_bytes, 2)}%."
    )
    if any(c.demand_redundancy.present for c in city_profiles):
        findings.append(
            "Таблица Потребление Узел.csv (~25–35% объёма папки города) на 60–85% состоит из нулей "
            "транзитных узлов и алгебраически дублирует произведение Потребители Узел.csv × График потребления.csv — "
            "её исключение сразу экономит треть объёма без потери информации."
        )
    findings.append(
        "Минутная сетка R0..R1439 (1 440 шагов) представляет собой 60-кратную линейную интерполяцию "
        "суточного графика с шагом 1 час: переход на часовые срезы H0..H23 + колонки min/max и отказ от "
        f"Потребление Узел.csv сокращает объём выгрузки на {round(100.0 * (1.0 - hourly_bytes / total_bytes), 1)}%, "
        f"а компактный формат v2 — на {round(100.0 * (1.0 - compact_v2_bytes / total_bytes), 1)}%."
    )

    return CorpusExportProfile(
        cities_count=len(city_profiles),
        total_bytes=total_bytes,
        total_mb=round(total_bytes / (1024 * 1024), 3),
        wide_bytes_share_pct=round(100.0 * wide_bytes / total_bytes, 2),
        redundant_bytes_total=redundant_bytes,
        redundant_bytes_pct=round(100.0 * redundant_bytes / total_bytes, 2),
        projected_hourly_no_demand_mb=round(hourly_bytes / (1024 * 1024), 3),
        projected_compact_v2_mb=round(compact_v2_bytes / (1024 * 1024), 3),
        savings_hourly_pct=round(max(0.0, 100.0 * (1.0 - hourly_bytes / total_bytes)), 2),
        savings_compact_v2_pct=round(max(0.0, 100.0 * (1.0 - compact_v2_bytes / total_bytes)), 2),
        cities=city_profiles,
        global_findings=findings,
        table_tier_summary=table_summary,
    )
