"""Вычисление и сохранение производных показателей из связанных таблиц AquaBit (по книге Walski et al. и СП 31.13330.2021).

Создаёт в папке `<city_out>/расчетные_параметры/` готовые инженерные таблицы:
1. `Узел_этажность_и_свободный_напор.csv` — этажность застройки (Hтреб = 10 + 4*(n-1)), свободный напор (HGL - Z),
   давление в барах, запас/дефицит напора, длительность дефицита (мин/сут) и суточный объём водоразбора (м3/сут).
2. `Свободный напор Узел.csv` — почасовая/поминутная матрица свободных напоров R0..R1439 (м вод. ст.).
3. `Труба_скорости_и_режимы_Walski.csv` — площадь сечения, объём воды в трубе (м3), индекс Q/D, точная скорость
   V = 4Q/(pi*D^2) (Walski p. 40, Eq. 2.9), скоростной напор V^2/(2g) (p. 43, Eq. 2.12), число Рейнольдса Re
   и режим течения (p. 42, Table 2.1), время пробега воды L/V (p. 67), оценка скорости по Walski (p. 292),
   а также потери напора dH и гидравлический уклон i (м/км) при корректных узлах Начало != Конец.
4. `Скорость Труба.csv` — знаковая матрица скоростей R0..R1439 (м/с) по всем участкам трубопроводов.
5. `Насос_рабочие_точки_и_мощность.csv` — интерполяция напора по кривой QH (Walski p. 58), моточасы, число пусков,
   суточная подача (м3/сут), гидравлическая мощность (кВт) и энергия (кВт*ч/сут, Walski p. 295).
6. `График_потребления_анализ_24ч.csv` — проверка нормировки K_сред ~ 1.0, коэффициенты часовой неравномерности K_max, K_min.
"""

from __future__ import annotations

import csv
import io
import json
import math
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field as dc_field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aquabit_ai.ingest.archive import _detect_csv_delimiter, _detect_encoding_raw
from aquabit_ai.ingest.city_folder import read_wide_timeseries_file, resolve_city_csv_route

G_ACCEL = 9.80665  # м/с^2
KINEMATIC_VISCOSITY_10C = 1.307e-6  # м^2/с (вода при 10 °C, Walski Ch. 2, Table 2.1)
BAR_PER_METER_WATER = 0.0980665  # бар на 1 м вод. ст.
NULL_TOKENS = {"", "null", "NULL", "None"}


@dataclass
class DerivedCityArtifacts:
    """Сводка рассчитанных и записанных производных таблиц по одному городу."""

    city_name: str
    output_dir: str
    files_created: dict[str, str] = dc_field(default_factory=dict)
    nodes_analyzed: int = 0
    deficit_nodes_count: int = 0
    excess_pressure_nodes_count: int = 0
    pipes_analyzed: int = 0
    high_velocity_pipes_count: int = 0
    stagnant_pipes_count: int = 0
    total_pipe_volume_m3: float = 0.0
    pumps_analyzed: int = 0
    total_pump_energy_kwh_day: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_static_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    enc, _, text, _ = _detect_encoding_raw(path.read_bytes())
    if not text:
        return ([], [])
    delim = _detect_csv_delimiter(text)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        return ([], [])
    return ([h.strip() for h in rows[0]], rows[1:])


def _num_or_none(val: str) -> float | None:
    s = val.strip()
    if s in NULL_TOKENS:
        return None
    try:
        f = float(s)
        return None if math.isnan(f) else f
    except ValueError:
        return None


def _classify_reynolds(re_val: float, v_abs_max: float) -> str:
    """Классификация режима течения по числу Рейнольдса (Walski Ch. 2, p. 42, Table 2.1)."""
    if v_abs_max <= 1e-9 or re_val <= 0.0:
        return "Застой (V = 0)"
    if re_val < 2000.0:
        return "Ламинарный (Re < 2000)"
    if re_val <= 4000.0:
        return "Переходный (2000 <= Re <= 4000)"
    return "Турбулентный (Re > 4000)"


def _classify_velocity_walski(v_abs_max: float) -> str:
    """Оценка максимальной скорости потока в трубе по рекомендациям Walski Ch. 8 (p. 292)."""
    if v_abs_max <= 1e-6:
        return "Нет движения (0 м/с)"
    if v_abs_max < 0.30:
        return "Малая скорость (< 0.3 м/с — риск застоя воды)"
    if v_abs_max <= 1.50:
        return "Штатная скорость распределительной сети (0.3–1.5 м/с)"
    if v_abs_max <= 3.00:
        return "Экономический диапазон напорных водоводов (1.5–3.0 м/с, Walski p. 292)"
    return "Повышенная скорость (> 3.0 м/с — риск высоких потерь и гидроудара!)"


def _write_wide_float_csv(
    out_path: Path,
    ids: list[str],
    r_headers: list[str],
    matrix: np.ndarray,
    null_mask: np.ndarray,
    decimals: int = 3,
) -> None:
    """Быстро записывает производную широкую матрицу ID,R0..R1439 с сохранением пустых ячеек."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = f"{{:.{decimals}f}}"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(["ID"] + r_headers) + "\n")
        for i, oid in enumerate(ids):
            row_vals = matrix[i]
            row_nulls = null_mask[i]
            if not np.any(row_nulls) and not np.any(np.isnan(row_vals)):
                formatted = np.char.mod(f"%.{decimals}f", row_vals)
                f.write(oid + "," + ",".join(formatted.tolist()) + "\n")
            else:
                cells = [
                    "" if (row_nulls[j] or math.isnan(float(row_vals[j]))) else fmt.format(float(row_vals[j]))
                    for j in range(len(r_headers))
                ]
                f.write(oid + "," + ",".join(cells) + "\n")


def compute_and_write_derived_city_tables(
    source_city_dir: Path,
    output_dir: Path,
    *,
    save_wide_matrices: bool = True,
) -> DerivedCityArtifacts:
    """Вычисляет все взаимно выводимые показатели для одного города и сохраняет их в CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    city_name = unicodedata.normalize("NFC", source_city_dir.name)
    res = DerivedCityArtifacts(city_name=city_name, output_dir=str(output_dir.resolve()))

    route_to_path: dict[str, Path] = {}
    for p in source_city_dir.iterdir():
        if p.is_file() and p.suffix.lower() == ".csv":
            r = resolve_city_csv_route(p)
            if r is not None:
                route_to_path[r] = p

    # Загружаем Напор Узел (нужен и для узлов, и для потерь напора по трубам)
    head_map: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    head_r_cols: list[str] = []
    if "wide/node_head.csv" in route_to_path:
        h_ing = read_wide_timeseries_file(route_to_path["wide/node_head.csv"], "wide/node_head.csv")
        if h_ing.wide_matrix is not None:
            h_ids = [str(x or "").strip() for x in h_ing.wide_matrix.id_list()]
            head_r_cols = list(h_ing.wide_matrix.step_columns)
            h_mat, h_null = h_ing.wide_matrix.to_numpy_with_null_mask()
            for idx, nid in enumerate(h_ids):
                if nid:
                    head_map[nid] = (h_mat[idx], h_null[idx])

    # Загружаем базовые нагрузки абонентов (композитное потребление узла, Walski p. 152)
    base_demand_sum: dict[str, float] = defaultdict(float)
    node_schedules: dict[str, list[str]] = defaultdict(list)
    if "demands.csv" in route_to_path:
        d_hdr, d_rows = _read_static_rows(route_to_path["demands.csv"])
        q_idx = next((i for i, h in enumerate(d_hdr) if "потреблен" in h.lower()), 1)
        s_idx = next((i for i, h in enumerate(d_hdr) if "график" in h.lower()), 2)
        for r in d_rows:
            if not r:
                continue
            nid = r[0].strip()
            qv = _num_or_none(r[q_idx]) if q_idx < len(r) else None
            if nid and qv is not None and qv > 0.0:
                base_demand_sum[nid] += qv
            if nid and s_idx < len(r) and r[s_idx].strip() not in NULL_TOKENS:
                sc = r[s_idx].strip()
                if sc not in node_schedules[nid]:
                    node_schedules[nid].append(sc)

    # Загружаем суточные объёмы из Потребление Узел (если есть)
    demand_wide_stats: dict[str, tuple[float, float, float]] = {}  # nid -> (daily_m3, q_mean, q_max)
    if "wide/node_demand.csv" in route_to_path:
        wd_ing = read_wide_timeseries_file(route_to_path["wide/node_demand.csv"], "wide/node_demand.csv")
        if wd_ing.wide_matrix is not None:
            wd_ids = [str(x or "").strip() for x in wd_ing.wide_matrix.id_list()]
            wd_mat, wd_null = wd_ing.wide_matrix.to_numpy_with_null_mask()
            n_st = max(1, wd_mat.shape[1])
            dt_hours = 24.0 / n_st
            for idx, nid in enumerate(wd_ids):
                valid = (~wd_null[idx]) & (~np.isnan(wd_mat[idx]))
                if np.any(valid):
                    vals = wd_mat[idx][valid]
                    demand_wide_stats[nid] = (
                        float(np.sum(vals) * dt_hours),
                        float(np.mean(vals)),
                        float(np.max(vals)),
                    )

    # =========================================================================
    # 1. УЗЛЫ: Этажность застройки, Свободный напор (HGL - Z), Запас/Дефицит
    # =========================================================================
    if "nodes.csv" in route_to_path:
        n_hdr, n_rows = _read_static_rows(route_to_path["nodes.csv"])
        elev_idx = next((i for i, h in enumerate(n_hdr) if "высот" in h.lower() or "отмет" in h.lower()), 1)
        req_idx = next((i for i, h in enumerate(n_hdr) if "давлен" in h.lower()), 2)

        node_records: list[dict[str, Any]] = []
        free_p_ids: list[str] = []
        free_p_rows: list[np.ndarray] = []
        free_p_nulls: list[np.ndarray] = []

        for r in n_rows:
            if not r:
                continue
            nid = r[0].strip()
            z_elev = _num_or_none(r[elev_idx]) if elev_idx < len(r) else None
            h_req = _num_or_none(r[req_idx]) if req_idx < len(r) else None

            if h_req is None or h_req <= 0.0:
                floors_exact = 0.0
                floors_int = 0
                bldg_type = "Транзитный узел (без абонентов)"
            elif h_req < 10.0:
                floors_exact = round(max(0.5, 1.0 + (h_req - 10.0) / 4.0), 2)
                floors_int = 1
                bldg_type = f"Ниже норматива 1 эт. ({h_req:g} м < 10 м)"
            else:
                floors_exact = round(1.0 + (h_req - 10.0) / 4.0, 2)
                floors_int = max(1, int(round(floors_exact)))
                if floors_int == 1:
                    bldg_type = "1 этаж (ИЖС / малоэтажная)"
                elif floors_int <= 5:
                    bldg_type = f"{floors_int} этажа(-ей) (мало-/среднеэтажная)"
                else:
                    bldg_type = f"{floors_int} этажей (многоэтажная)"

            hgl_min = hgl_max = free_min = free_mean = free_max = p_max_bar = margin_min = None
            deficit_minutes = 0
            status = "Нет ряда Напор Узел"

            if nid in head_map and z_elev is not None:
                h_row, h_nmask = head_map[nid]
                valid = (~h_nmask) & (~np.isnan(h_row))
                f_row = h_row - z_elev
                if save_wide_matrices and (h_req is not None and h_req > 0.0):
                    free_p_ids.append(nid)
                    free_p_rows.append(f_row)
                    free_p_nulls.append(h_nmask | np.isnan(h_row))

                if np.any(valid):
                    v_hgl = h_row[valid]
                    v_free = f_row[valid]
                    hgl_min = round(float(np.min(v_hgl)), 3)
                    hgl_max = round(float(np.max(v_hgl)), 3)
                    free_min = round(float(np.min(v_free)), 3)
                    free_mean = round(float(np.mean(v_free)), 3)
                    free_max = round(float(np.max(v_free)), 3)
                    p_max_bar = round(free_max * BAR_PER_METER_WATER, 3)

                    if h_req is not None and h_req > 0.0:
                        margin_min = round(free_min - h_req, 3)
                        step_mins = 1440.0 / max(1, len(h_row))
                        deficit_minutes = int(round(float(np.sum(v_free < h_req)) * step_mins))
                        if margin_min < 0.0:
                            res.deficit_nodes_count += 1
                            status = f"ДЕФИЦИТ НАПОРА ({margin_min:+.2f} м)"
                        elif free_max > 60.0:
                            res.excess_pressure_nodes_count += 1
                            status = f"ИЗБЫТОЧНЫЙ НАПОР > 60 м ({free_max:.1f} м)"
                        else:
                            status = "Норма (напор обеспечен)"
                    else:
                        status = "Транзитный узел"

            d_m3, _, q_pk = demand_wide_stats.get(nid, (0.0, 0.0, 0.0))
            node_records.append({
                "ID": nid,
                "Высота_Z_м": z_elev,
                "Требуемое_давление_м": h_req,
                "Расчетная_этажность_точная": floors_exact,
                "Этажность_дома": floors_int,
                "Категория_застройки": bldg_type,
                "Базовое_потребление_сумма_м3_ч": round(base_demand_sum.get(nid, 0.0), 4),
                "Пиковый_расход_м3_ч": round(q_pk, 3),
                "Суточный_объем_м3_сут": round(d_m3, 2),
                "Графики_потребления": ",".join(node_schedules.get(nid, [])),
                "Пьезометр_HGL_мин_м": hgl_min,
                "Пьезометр_HGL_макс_м": hgl_max,
                "Свободный_напор_мин_м": free_min,
                "Свободный_напор_сред_м": free_mean,
                "Свободный_напор_макс_м": free_max,
                "Макс_давление_бар": p_max_bar,
                "Запас_напора_мин_м": margin_min,
                "Длительность_дефицита_мин_сут": deficit_minutes,
                "Статус_напора": status,
            })

        res.nodes_analyzed = len(node_records)
        nodes_out = output_dir / "Узел_этажность_и_свободный_напор.csv"
        pd.DataFrame(node_records).to_csv(nodes_out, index=False, encoding="utf-8-sig")
        res.files_created["nodes_derived"] = str(nodes_out)

        if save_wide_matrices and free_p_ids and head_r_cols:
            fp_out = output_dir / "Свободный напор Узел.csv"
            _write_wide_float_csv(
                fp_out,
                free_p_ids,
                head_r_cols,
                np.vstack(free_p_rows),
                np.vstack(free_p_nulls),
                decimals=2,
            )
            res.files_created["wide_free_pressure"] = str(fp_out)

    # =========================================================================
    # 2. ТРУБЫ: Скорость V = 4Q/(pi*D^2), Q/D, Рейнольдс Re, Время пробега L/V
    # =========================================================================
    if "pipes.csv" in route_to_path:
        p_hdr, p_rows = _read_static_rows(route_to_path["pipes.csv"])
        s_idx = next((i for i, h in enumerate(p_hdr) if "начал" in h.lower()), 1)
        e_idx = next((i for i, h in enumerate(p_hdr) if "конец" in h.lower()), 2)
        d_idx = next((i for i, h in enumerate(p_hdr) if "диаметр" in h.lower()), 3)
        l_idx = next((i for i, h in enumerate(p_hdr) if "длин" in h.lower()), 4)
        r_idx = next((i for i, h in enumerate(p_hdr) if "шероховат" in h.lower()), 5)

        pflow_map: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        pflow_r_cols: list[str] = []
        if "wide/pipe_flow.csv" in route_to_path:
            pf_ing = read_wide_timeseries_file(route_to_path["wide/pipe_flow.csv"], "wide/pipe_flow.csv")
            if pf_ing.wide_matrix is not None:
                pf_ids = [str(x or "").strip() for x in pf_ing.wide_matrix.id_list()]
                pflow_r_cols = list(pf_ing.wide_matrix.step_columns)
                pf_mat, pf_null = pf_ing.wide_matrix.to_numpy_with_null_mask()
                for idx, pid in enumerate(pf_ids):
                    if pid:
                        pflow_map[pid] = (pf_mat[idx], pf_null[idx])

        pipe_records: list[dict[str, Any]] = []
        vel_ids: list[str] = []
        vel_rows: list[np.ndarray] = []
        vel_nulls: list[np.ndarray] = []

        for r in p_rows:
            if not r:
                continue
            pid = r[0].strip()
            n_start = r[s_idx].strip() if s_idx < len(r) else ""
            n_end = r[e_idx].strip() if e_idx < len(r) else ""
            d_mm = _num_or_none(r[d_idx]) if d_idx < len(r) else None
            length_m = _num_or_none(r[l_idx]) if l_idx < len(r) else None
            rough = _num_or_none(r[r_idx]) if r_idx < len(r) else None

            d_m = (d_mm / 1000.0) if (d_mm is not None and d_mm > 0.0) else None
            area_m2 = (math.pi * d_m * d_m / 4.0) if d_m is not None else None
            vol_m3 = (area_m2 * length_m) if (area_m2 is not None and length_m is not None and length_m > 0.0) else 0.0
            res.total_pipe_volume_m3 += vol_m3

            q_abs_mean = q_abs_max = q_div_d = v_min = v_mean = v_max = hv_max = re_max = travel_min = None
            rev_steps = 0
            regime_re = "Нет данных потока"
            walski_band = "Нет данных потока"

            if pid in pflow_map and area_m2 is not None and d_m is not None and d_mm is not None:
                q_row, q_nmask = pflow_map[pid]
                valid = (~q_nmask) & (~np.isnan(q_row))
                # Walski Ch. 2, p. 40, Eq. 2.9: V [м/с] = (Q [м3/ч] / 3600) / A [м2]
                v_signed = (q_row / 3600.0) / area_m2
                if save_wide_matrices and pflow_r_cols:
                    vel_ids.append(pid)
                    vel_rows.append(v_signed)
                    vel_nulls.append(q_nmask | np.isnan(q_row))

                if np.any(valid):
                    vq = q_row[valid]
                    vv_abs = np.abs(v_signed[valid])
                    q_abs_mean = round(float(np.mean(np.abs(vq))), 3)
                    q_abs_max = round(float(np.max(np.abs(vq))), 3)
                    q_div_d = round(q_abs_max / d_mm, 4)  # упрощённый индекс |Q_max| / D
                    v_min = round(float(np.min(vv_abs)), 4)
                    v_mean = round(float(np.mean(vv_abs)), 4)
                    v_max = round(float(np.max(vv_abs)), 4)
                    # Walski p. 43, Eq. 2.12: скоростной напор V^2 / (2g)
                    hv_max = round((v_max * v_max) / (2.0 * G_ACCEL), 4)
                    # Walski p. 42, Table 2.1: число Рейнольдса Re = V * D / nu
                    re_max = round((v_max * d_m) / KINEMATIC_VISCOSITY_10C, 0)
                    regime_re = _classify_reynolds(re_max, v_max)
                    walski_band = _classify_velocity_walski(v_max)
                    rev_steps = int(np.sum(vq < 0.0))

                    if v_max > 3.0:
                        res.high_velocity_pipes_count += 1
                    elif v_max < 0.30:
                        res.stagnant_pipes_count += 1

                    if length_m is not None and length_m > 0.0 and v_mean > 1e-6:
                        # Walski Ch. 2.9, p. 67: время пробега воды по участку t = L / V
                        travel_min = round(length_m / (v_mean * 60.0), 2)

            # Потери напора dH и гидравлический уклон i (м/км), если Начало и Конец различны и есть в Напор Узел
            dh_max_m = slope_m_per_km = None
            topo_note = "OK"
            if n_start and n_start == n_end:
                topo_note = "Петля экспорта (Начало == Конец)"
            elif n_start in head_map and n_end in head_map:
                h1, n1 = head_map[n_start]
                h2, n2 = head_map[n_end]
                both_ok = (~n1) & (~n2) & (~np.isnan(h1)) & (~np.isnan(h2))
                if np.any(both_ok):
                    dh_arr = np.abs(h1[both_ok] - h2[both_ok])
                    dh_max_m = round(float(np.max(dh_arr)), 3)
                    if length_m is not None and length_m > 0.0:
                        slope_m_per_km = round((dh_max_m / length_m) * 1000.0, 3)

            pipe_records.append({
                "ID": pid,
                "Начало": n_start,
                "Конец": n_end,
                "Диаметр_мм": d_mm,
                "Длина_м": length_m,
                "Шероховатость": rough,
                "Площадь_сечения_м2": round(area_m2, 6) if area_m2 is not None else None,
                "Объем_трубы_м3": round(vol_m3, 3),
                "Расход_сред_абс_м3_ч": q_abs_mean,
                "Расход_макс_абс_м3_ч": q_abs_max,
                "Упрощенный_индекс_Qмакс_делить_D": q_div_d,
                "Скорость_мин_м_с": v_min,
                "Скорость_сред_м_с": v_mean,
                "Скорость_макс_м_с": v_max,
                "Скоростной_напор_V2_2g_м": hv_max,
                "Число_Рейнольдса_Re_макс": re_max,
                "Режим_течения_Re": regime_re,
                "Время_пробега_воды_мин": travel_min,
                "Шагов_обратного_потока": rev_steps,
                "Потери_напора_макс_м": dh_max_m,
                "Гидравлический_уклон_макс_м_км": slope_m_per_km,
                "Оценка_скорости_Walski": walski_band,
                "Статус_топологии": topo_note,
            })

        res.pipes_analyzed = len(pipe_records)
        res.total_pipe_volume_m3 = round(res.total_pipe_volume_m3, 2)
        pipes_out = output_dir / "Труба_скорости_и_режимы_Walski.csv"
        pd.DataFrame(pipe_records).to_csv(pipes_out, index=False, encoding="utf-8-sig")
        res.files_created["pipes_derived"] = str(pipes_out)

        if save_wide_matrices and vel_ids and pflow_r_cols:
            vel_out = output_dir / "Скорость Труба.csv"
            _write_wide_float_csv(
                vel_out,
                vel_ids,
                pflow_r_cols,
                np.vstack(vel_rows),
                np.vstack(vel_nulls),
                decimals=4,
            )
            res.files_created["wide_pipe_velocity"] = str(vel_out)

    # =========================================================================
    # 3. НАСОСЫ: Рабочая точка на кривой QH, моточасы, пуски и мощность (кВт)
    # =========================================================================
    if "pumps.csv" in route_to_path:
        pm_hdr, pm_rows = _read_static_rows(route_to_path["pumps.csv"])
        c_idx = next((i for i, h in enumerate(pm_hdr) if "крив" in h.lower()), 3)

        curves_pts: dict[str, list[tuple[float, float]]] = defaultdict(list)
        if "pump_curves.csv" in route_to_path:
            qh_hdr, qh_rows = _read_static_rows(route_to_path["pump_curves.csv"])
            for r in qh_rows:
                if len(r) >= 3:
                    cid = r[0].strip()
                    qx = _num_or_none(r[1])
                    hy = _num_or_none(r[2])
                    if cid and qx is not None and hy is not None:
                        curves_pts[cid].append((qx, hy))
            for cid in curves_pts:
                curves_pts[cid].sort(key=lambda pair: pair[0])

        pmflow_map: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        if "wide/pump_flow.csv" in route_to_path:
            pmf_ing = read_wide_timeseries_file(route_to_path["wide/pump_flow.csv"], "wide/pump_flow.csv")
            if pmf_ing.wide_matrix is not None:
                pm_ids = [str(x or "").strip() for x in pmf_ing.wide_matrix.id_list()]
                pm_mat, pm_null = pmf_ing.wide_matrix.to_numpy_with_null_mask()
                for idx, pmid in enumerate(pm_ids):
                    if pmid:
                        pmflow_map[pmid] = (pm_mat[idx], pm_null[idx])

        pump_records: list[dict[str, Any]] = []
        for r in pm_rows:
            if not r:
                continue
            pmid = r[0].strip()
            cid = r[c_idx].strip() if c_idx < len(r) else ""
            pts = curves_pts.get(cid, [])
            qx_arr = np.array([p[0] for p in pts], dtype=np.float64) if pts else np.array([])
            hy_arr = np.array([p[1] for p in pts], dtype=np.float64) if pts else np.array([])
            h_shutoff = float(hy_arr[0]) if (pts and qx_arr[0] == 0.0) else (float(hy_arr[0]) if pts else None)
            q_curve_max = float(qx_arr[-1]) if pts else None

            if pmid not in pmflow_map:
                # Насос был отфильтрован из Поток Насос как полностью нулевой резервный!
                pump_records.append({
                    "ID": pmid,
                    "Кривая_QH": cid,
                    "Точек_кривой_QH": len(pts),
                    "Режим_работы": "В резерве (выключен все сутки, Q = 0)",
                    "Моточасов_в_сутки": 0.0,
                    "Число_пусков_за_сутки": 0,
                    "Подача_рабочая_сред_м3_ч": 0.0,
                    "Подача_макс_м3_ч": 0.0,
                    "Суточная_подача_м3_сут": 0.0,
                    "Напор_холостого_хода_H0_м": h_shutoff,
                    "Расчетный_напор_TDH_сред_м": None,
                    "Гидравлическая_мощность_сред_кВт": 0.0,
                    "Гидравлическая_мощность_макс_кВт": 0.0,
                    "Гидравлическая_энергия_кВтч_сут": 0.0,
                    "Положение_рабочей_точки": "Насос закрыт",
                })
                continue

            q_row, q_nmask = pmflow_map[pmid]
            valid = (~q_nmask) & (~np.isnan(q_row))
            n_st = max(1, len(q_row))
            dt_h = 24.0 / n_st
            vq = q_row[valid]
            active_mask = vq > 1e-6

            if not np.any(active_mask):
                pump_records.append({
                    "ID": pmid,
                    "Кривая_QH": cid,
                    "Точек_кривой_QH": len(pts),
                    "Режим_работы": "В резерве (выключен все сутки, Q = 0)",
                    "Моточасов_в_сутки": 0.0,
                    "Число_пусков_за_сутки": 0,
                    "Подача_рабочая_сред_м3_ч": 0.0,
                    "Подача_макс_м3_ч": 0.0,
                    "Суточная_подача_м3_сут": 0.0,
                    "Напор_холостого_хода_H0_м": h_shutoff,
                    "Расчетный_напор_TDH_сред_м": None,
                    "Гидравлическая_мощность_сред_кВт": 0.0,
                    "Гидравлическая_мощность_макс_кВт": 0.0,
                    "Гидравлическая_энергия_кВтч_сут": 0.0,
                    "Положение_рабочей_точки": "Насос закрыт",
                })
                continue

            q_active = vq[active_mask]
            run_hours = round(float(np.sum(active_mask)) * dt_h, 2)
            # Число включений (переходов 0 -> >0)
            on_int = active_mask.astype(np.int8)
            starts = int(np.sum((on_int[1:] == 1) & (on_int[:-1] == 0))) + (1 if on_int[0] == 1 and not np.all(active_mask) else 0)
            mode_str = "Постоянно в работе (24 ч)" if np.all(active_mask) else f"Циклическая работа ({run_hours:g} ч/сут)"

            q_mean_act = round(float(np.mean(q_active)), 3)
            q_max_act = round(float(np.max(q_active)), 3)
            vol_day = round(float(np.sum(q_active)) * dt_h, 2)

            tdh_mean = p_kw_mean = p_kw_max = energy_kwh = None
            curve_pos = "Недостаточно точек кривой (<2)"
            if len(pts) >= 2:
                h_interp = np.interp(q_active, qx_arr, hy_arr)
                # Полезная гидравлическая мощность: N [кВт] = rho * g * (Q / 3600) * H / 1000
                p_kw_arr = (G_ACCEL * q_active * h_interp) / 3600.0
                tdh_mean = round(float(np.mean(h_interp)), 3)
                p_kw_mean = round(float(np.mean(p_kw_arr)), 3)
                p_kw_max = round(float(np.max(p_kw_arr)), 3)
                energy_kwh = round(float(np.sum(p_kw_arr)) * dt_h, 2)
                res.total_pump_energy_kwh_day += energy_kwh
                if q_curve_max and q_max_act > q_curve_max:
                    curve_pos = f"Правее паспортной кривой (Qмакс={q_max_act} > {q_curve_max:g} м3/ч!)"
                elif q_curve_max and q_mean_act < 0.25 * q_curve_max:
                    curve_pos = "Левая зона малых подач (<25% Qпасп — низкий КПД, Walski p. 295)"
                else:
                    curve_pos = "Рабочая зона характеристики Q-H"
            elif len(pts) == 1:
                h_only = float(hy_arr[0])
                tdh_mean = h_only
                p_kw_mean = round((G_ACCEL * q_mean_act * h_only) / 3600.0, 3)
                p_kw_max = round((G_ACCEL * q_max_act * h_only) / 3600.0, 3)
                energy_kwh = round(p_kw_mean * run_hours, 2)
                res.total_pump_energy_kwh_day += energy_kwh
                curve_pos = "Задана только 1 расчётная точка Q-H"

            pump_records.append({
                "ID": pmid,
                "Кривая_QH": cid,
                "Точек_кривой_QH": len(pts),
                "Режим_работы": mode_str,
                "Моточасов_в_сутки": run_hours,
                "Число_пусков_за_сутки": starts,
                "Подача_рабочая_сред_м3_ч": q_mean_act,
                "Подача_макс_м3_ч": q_max_act,
                "Суточная_подача_м3_сут": vol_day,
                "Напор_холостого_хода_H0_м": h_shutoff,
                "Расчетный_напор_TDH_сред_м": tdh_mean,
                "Гидравлическая_мощность_сред_кВт": p_kw_mean,
                "Гидравлическая_мощность_макс_кВт": p_kw_max,
                "Гидравлическая_энергия_кВтч_сут": energy_kwh,
                "Положение_рабочей_точки": curve_pos,
            })

        res.pumps_analyzed = len(pump_records)
        res.total_pump_energy_kwh_day = round(res.total_pump_energy_kwh_day, 2)
        pumps_out = output_dir / "Насос_рабочие_точки_и_мощность.csv"
        pd.DataFrame(pump_records).to_csv(pumps_out, index=False, encoding="utf-8-sig")
        res.files_created["pumps_derived"] = str(pumps_out)

    # =========================================================================
    # 4. ГРАФИКИ ПОТРЕБЛЕНИЯ: Коэффициенты неравномерности K_min, K_mean, K_max
    # =========================================================================
    if "irregularity_curves.csv" in route_to_path:
        sc_hdr, sc_rows = _read_static_rows(route_to_path["irregularity_curves.csv"])
        by_curve: dict[str, list[float]] = defaultdict(list)
        for r in sc_rows:
            if len(r) >= 2:
                cid = r[0].strip()
                kv = _num_or_none(r[1])
                if cid and kv is not None:
                    by_curve[cid].append(kv)

        sched_records = []
        for cid, vals in sorted(by_curve.items()):
            arr = np.array(vals, dtype=np.float64)
            k_min = float(np.min(arr))
            k_mean = float(np.mean(arr))
            k_max = float(np.max(arr))
            peak_hour = int(np.argmax(arr))
            sched_records.append({
                "ID": cid,
                "Часовых_строк": len(vals),
                "Полнота_24ч": "ДА" if len(vals) == 24 else f"НЕТ ({len(vals)} != 24)",
                "K_мин": round(k_min, 5),
                "K_сред": round(k_mean, 5),
                "K_макс": round(k_max, 5),
                "Час_максимума": f"{peak_hour:02d}:00",
                "Размах_неравномерности_Kмакс_Kмин": round(k_max / k_min, 3) if k_min > 1e-6 else None,
                "Нормирован_к_1": "ДА" if abs(k_mean - 1.0) <= 0.03 else f"Отклонение ({k_mean:.3f})",
            })
        sched_out = output_dir / "График_потребления_анализ_24ч.csv"
        pd.DataFrame(sched_records).to_csv(sched_out, index=False, encoding="utf-8-sig")
        res.files_created["schedules_derived"] = str(sched_out)

    # Манифест формул и первоисточников (трассируемость всех производных величин)
    formulas_manifest = {
        "city_name": city_name,
        "formulas_applied": {
            "pipe_velocity_m_s": "V = 4 * (Q / 3600) / (pi * (D / 1000)^2) — Walski et al., Ch. 2, p. 40, Eq. 2.9",
            "pipe_q_over_d_index": "|Q_max| / D_mm — упрощённый удельный индекс расхода на единицу диаметра",
            "velocity_head_m": "h_v = V^2 / (2 * g), g = 9.80665 м/с^2 — Walski et al., Ch. 2.3, p. 43, Eq. 2.12",
            "reynolds_number": "Re = V * (D / 1000) / nu, nu(10°C) = 1.307e-6 м^2/с — Walski et al., Ch. 2, p. 42, Table 2.1",
            "pipe_travel_time_min": "t = L / (V_mean * 60) — Walski et al., Ch. 2.9, p. 67",
            "free_pressure_head_m": "H_free = HGL - Z — Walski et al., Ch. 2.3, p. 43, Eq. 2.12",
            "building_storeys": "n = 1 + (H_req - 10) / 4 — СП 31.13330.2021, п. 5.11",
            "pump_hydraulic_power_kw": "N_hyd = rho * g * (Q / 3600) * H(Q) / 1000 — Walski et al., Ch. 2.7 p. 58 & Ch. 8.3 p. 295",
        },
        "summary": res.to_dict(),
    }
    manifest_out = output_dir / "derived_formulas_manifest.json"
    manifest_out.write_text(json.dumps(formulas_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    res.files_created["formulas_manifest"] = str(manifest_out)

    return res
