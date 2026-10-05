"""Analytics Engine: детерминированный слой.

ВАЖНО (roadmap, п.8): все числа, отклонения, Top-N проблем и сравнения
считаются ЗДЕСЬ, а не языковой моделью. LLM получает только результат
этой работы в виде компактного контекста и evidence-ссылок.

Единицы: м³/с внутри симуляции → л/с в отчётах; давление — м вод.ст.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import wntr

from . import common


# ────────────────────────────────────────────────────────────── загрузка

@dataclass
class ScenarioResults:
    """Результаты одного сценария: сеть + временные ряды."""
    scenario_dir: Path
    scenario: dict
    wn: "wntr.network.WaterNetworkModel"
    pressure: pd.DataFrame      # узлы × время, м вод.ст.
    head: pd.DataFrame
    demand: pd.DataFrame        # л/с
    flowrate: pd.DataFrame      # л/с
    velocity: pd.DataFrame      # м/с
    link_status: pd.DataFrame
    time_h: np.ndarray

    @property
    def junction_ids(self) -> list[str]:
        return list(self.wn.junction_name_list)

    @property
    def alert_ids(self) -> list[str]:
        return [n for n in self.wn.node_name_list if self.wn.get_node(n).node_type in ("Junction", "Tank")]


def load_results(scenario_dir: Path | str) -> ScenarioResults:
    scenario_dir = Path(scenario_dir)
    if not scenario_dir.is_absolute():
        scenario_dir = common.ROOT / scenario_dir
    scenario = common.read_json(scenario_dir / "scenario.json")
    wn = wntr.network.WaterNetworkModel(str(scenario_dir / "network.inp"))

    res_dir = scenario_dir / "results"
    read = lambda name: pd.read_csv(res_dir / f"{name}.csv", index_col=0)
    pressure = read("pressure")
    head = read("head")
    demand = read("demand") * 1000.0      # м³/с → л/с
    flow = read("flowrate") * 1000.0
    velocity = read("velocity")
    status = read("link_status")
    time_h = np.asarray(pressure.index, dtype=float)
    return ScenarioResults(scenario_dir, scenario, wn, pressure, head, demand,
                           flow, velocity, status, time_h)


# ─────────────────────────────────── учёт дефицита подачи (PDA-режим)

def expected_demand_lps(res: ScenarioResults) -> pd.DataFrame:
    """Требуемый (расчётный) спрос по узлам с учётом графиков водопотребления, л/с.

    В PDA-режиме сравнение «требовалось / подано» даёт недоподачу —
    это главный честный признак аварийного режима.
    """
    wn = res.wn
    times_sec = np.asarray(res.time_h, dtype=float) * 3600.0
    data = {}
    for nid in res.junction_ids:
        node = wn.get_node(nid)
        vals = []
        for t in times_sec:
            v = 0.0
            try:
                for dl in node.demand_timeseries_list:
                    v += float(dl.at(float(t)))
            except Exception:  # noqa: BLE001 — паттерн может не покрывать конец суток
                v = float("nan")
            vals.append(v * 1000.0)
        data[nid] = vals
    return pd.DataFrame(data, index=res.time_h)


def demand_deficit_lps(res: ScenarioResults) -> pd.DataFrame:
    """Недоподача по узлам, л/с (>= 0)."""
    exp = expected_demand_lps(res)
    delivered = res.demand.reindex(columns=exp.columns)
    return (exp - delivered).clip(lower=0.0)


# ────────────────────────────────────────────────────────── статика сети

def network_summary(wn) -> dict:
    total_len = float(sum(wn.get_link(l).length for l in wn.pipe_name_list)) if wn.pipe_name_list else 0.0
    return {
        "junctions": len(wn.junction_name_list),
        "pipes": len(wn.pipe_name_list),
        "pumps": len(wn.pump_name_list),
        "tanks": len(wn.tank_name_list),
        "reservoirs": len(wn.reservoir_name_list),
        "valves": len(getattr(wn, "valve_name_list", [])),
        "total_pipe_length_km": round(total_len / 1000.0, 3),
    }


def node_static(wn, nid: str) -> dict:
    n = wn.get_node(nid)
    t = n.node_type
    d = {"type": t.lower()}
    if t == "Junction":
        d["elevation_m"] = round(float(n.elevation), 2)
        base = float(n.demand_timeseries_list[0].base_value) * 1000.0 if len(n.demand_timeseries_list) else 0.0
        d["base_demand_lps"] = round(base, 2)
        d["pattern"] = getattr(n.demand_timeseries_list[0].pattern, "name", None) if len(n.demand_timeseries_list) else None
    elif t == "Tank":
        d.update({"elevation_m": round(float(n.elevation), 2), "init_level_m": round(float(n.init_level), 2),
                  "min_level_m": round(float(n.min_level), 2), "max_level_m": round(float(n.max_level), 2),
                  "diameter_m": round(float(n.diameter), 2)})
    elif t == "Reservoir":
        d["head_m"] = round(float(n.head_timeseries.base_value), 2)
    return d


def link_static(wn, lid: str) -> dict:
    l = wn.get_link(lid)
    d = {"type": l.link_type.lower(), "from": l.start_node_name, "to": l.end_node_name}
    if l.link_type == "Pipe":
        d.update({"length_m": round(float(l.length), 1), "diameter_mm": round(float(l.diameter) * 1000, 0),
                  "roughness_c": round(float(l.roughness), 1),
                  "status": "open" if str(l.initial_status).lower().endswith("open") else "closed"})
        area = math.pi * (float(l.diameter) ** 2) / 4.0
        d["rel_capacity_lps_at_1ms"] = round(area * 1000.0, 1)
    elif l.link_type == "Pump":
        d["curve"] = l.pump_curve_name
        try:
            pts = wn.get_curve(l.pump_curve_name).points
            d["curve_points"] = [(round(float(x) * 1000, 1), round(float(y), 1)) for x, y in pts]
            d["max_curve_flow_lps"] = round(float(pts[-1][0]) * 1000, 1)
        except Exception:
            d["curve_points"] = []
    return d


def neighbors(wn, nid: str, depth: int = 1) -> list[dict]:
    """Связность: какие объекты примыкают к узлу (по графу, не по картинке)."""
    seen_nodes, seen_links, frontier = {nid}, set(), [nid]
    for _ in range(max(depth, 0)):
        nxt = []
        for node in frontier:
            for lid in wn.get_links_for_node(node):
                if lid in seen_links:
                    continue
                seen_links.add(lid)
                l = wn.get_link(lid)
                other = l.end_node_name if l.start_node_name == node else l.start_node_name
                if other not in seen_nodes:
                    seen_nodes.add(other)
                    nxt.append(other)
        frontier = nxt
    out = []
    for lid in sorted(seen_links):
        st = link_static(wn, lid)
        out.append({"link": lid, **st})
    for n in sorted(seen_nodes - {nid}):
        out.append({"node": n, **node_static(wn, n)})
    return out


# ────────────────────────────────────────────────────── KPI и профили

def _series_stats(s: pd.Series, unit: str) -> dict:
    return {
        "min": round(float(s.min()), 2), "max": round(float(s.max()), 2),
        "mean": round(float(s.mean()), 2),
        "t_min_h": round(float(s.idxmin()), 1), "t_max_h": round(float(s.idxmax()), 1),
        "unit": unit,
    }


def compute_kpis(res: ScenarioResults) -> dict:
    pr, dm, fl, ve = res.pressure, res.demand, res.flowrate, res.velocity
    j = res.junction_ids
    kpi = {
        "min_pressure_m": round(float(pr[j].min().min()), 2),
        "min_pressure_node": str(pr[j].min().idxmin()),
        "max_pressure_m": round(float(pr[j].max().max()), 2),
        "max_pressure_node": str(pr[j].max().idxmax()),
        "mean_pressure_m": round(float(pr[j].mean().mean()), 2),
        "max_velocity_mps": round(float(ve.max().max()), 2),
        "max_velocity_link": str(ve.max().idxmax()),
        "total_demand_m3": round(float(dm[j].sum().sum()) * 3600 / 1000.0, 1),
        "peak_demand_lps": round(float(dm[j].sum(axis=1).max()), 1),
        "peak_demand_time_h": round(float(dm[j].sum(axis=1).idxmax()), 1),
        "min_demand_lps": round(float(dm[j].sum(axis=1).min()), 1),
        "source_supply_m3": round(float(dm[[n for n in res.wn.node_name_list
                                            if res.wn.get_node(n).node_type in ("Reservoir", "Tank")]].sum().sum() * 3600 / -1000.0), 1),
    }
    # время, когда давление в узле минимально
    tmin = pr[j].min().idxmin()
    node = pr[j].min().idxmin()
    kpi["min_pressure_time_h"] = round(float(pr[node].idxmin()), 1)
    # уровни резервуаров
    tanks = {}
    for tid in res.wn.tank_name_list:
        s = pr[tid]
        t = res.wn.get_node(tid)
        tanks[tid] = {
            "level_min_m": round(float(s.min()), 2), "level_max_m": round(float(s.max()), 2),
            "level_start_m": round(float(s.iloc[0]), 2), "level_end_m": round(float(s.iloc[-1]), 2),
            "min_level_setting_m": round(float(t.min_level), 2), "max_level_setting_m": round(float(t.max_level), 2),
            "time_at_min_h": round(float((s <= float(t.min_level) + 0.05).sum()), 1),
        }
    if tanks:
        kpi["tanks"] = tanks
    try:
        deficit = demand_deficit_lps(res)
        kpi["unserved_volume_m3"] = round(float(deficit.sum().sum()), 1)
        if kpi["unserved_volume_m3"] > 0:
            worst = deficit.sum().sort_values(ascending=False)
            kpi["unserved_worst_nodes"] = [{"node": str(n), "unserved_m3": round(float(v), 1),
                                            "max_deficit_lps": round(float(deficit[n].max()), 2)}
                                           for n, v in worst.head(5).items() if v > 0.01]
    except Exception:  # noqa: BLE001
        kpi["unserved_volume_m3"] = None
    return kpi


def node_profile(res: ScenarioResults, nid: str) -> dict:
    out = {"id": nid, **node_static(res.wn, nid)}
    if nid in res.pressure.columns:
        out["pressure"] = _series_stats(res.pressure[nid], "м вод.ст.")
    if nid in res.demand.columns:
        out["demand"] = _series_stats(res.demand[nid], "л/с")
    return out


def link_profile(res: ScenarioResults, lid: str) -> dict:
    out = {"id": lid, **link_static(res.wn, lid)}
    if lid in res.flowrate.columns:
        f = res.flowrate[lid]
        out["flow"] = _series_stats(f, "л/с")
        out["flow"]["sign_changes"] = int((np.sign(f).diff().abs() > 0).sum())
        out["flow"]["reverse_hours"] = int((f < -1e-6).sum())
    if lid in res.velocity.columns:
        out["velocity"] = _series_stats(res.velocity[lid], "м/с")
    if lid in res.link_status.columns:
        out["closed_hours"] = int((res.link_status[lid] < 0.5).sum())
    return out


def object_profile(res: ScenarioResults, oid: str) -> dict:
    """Профиль любого объекта: узел или участок."""
    if oid in res.wn.node_name_list:
        return node_profile(res, oid)
    if oid in res.wn.link_name_list:
        return link_profile(res, oid)
    raise KeyError(f"Объект {oid} не найден в сети")


# ────────────────────────────────────────────────────── правила / алерты

def _resolve_threshold(raw, ctx: dict) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        expr = raw
        for k, v in ctx.items():
            expr = expr.replace(k, f"({v})")
        try:
            return float(eval(expr, {"__builtins__": {}}, {}))
        except Exception:
            return None
    return None


class EvidenceFactory:
    """Нумерует факты: E-001, E-002 ... Каждый факт машиночитаем и имеет текст."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def add(self, *, obj: str, metric: str, value, unit: str, statement: str,
            time_h: float | None = None, threshold_rule: str | None = None,
            extra: dict | None = None) -> str:
        eid = f"E-{len(self.items) + 1:03d}"
        self.items[eid] = {
            "evidence_id": eid, "object": obj, "metric": metric, "value": value,
            "unit": unit, "time_h": time_h, "threshold_rule": threshold_rule,
            "statement": statement, **(extra or {}),
        }
        return eid


def detect_alerts(res: ScenarioResults, thresholds: dict, ev: EvidenceFactory) -> list[dict]:
    """Применяет пороговые правила. Возвращает список алертов со ссылками на evidence."""
    rules = {r["id"]: r for r in thresholds["rules"]}
    alerts: list[dict] = []
    pr, dm, fl, ve, st = res.pressure, res.demand, res.flowrate, res.velocity, res.link_status
    step_h = float(res.time_h[1] - res.time_h[0]) if len(res.time_h) > 1 else 1.0

    def dur_hours(mask) -> float:
        """Длительность в часах: число шагов ниже порога × шаг расчёта (не больше горизонта)."""
        horizon = float(res.time_h[-1] - res.time_h[0]) if len(res.time_h) > 1 else 24.0
        return round(min(float(np.asarray(mask).sum()) * step_h, horizon), 2)

    def steps(mask) -> int:
        return int(np.asarray(mask).sum())

    def add_alert(rule_id: str, obj: str, value, unit: str, t: float, eid: str, text: str, **kw):
        alerts.append({
            "alert_id": f"A-{len(alerts) + 1:03d}",
            "rule": rule_id, "severity": rules[rule_id]["severity"], "object": obj,
            "value": value, "unit": unit, "time_h": round(float(t), 1),
            "evidence_id": eid, "statement": text, **kw,
        })

    # --- давление
    for nid in res.junction_ids:
        s = pr[nid]
        for rule_id in ("low_pressure_critical", "low_pressure_warning"):
            lim = float(rules[rule_id]["value"])
            mask = s < lim
            if mask.any():
                t = float(s[mask].idxmin())
                v = round(float(s[t]), 2)
                eid = ev.add(obj=nid, metric="pressure", value=v, unit="м вод.ст.", time_h=t,
                             threshold_rule=rule_id,
                             statement=(f"{nid}: давление {v} м вод.ст. в {t:g} ч (норматив {lim} м); "
                                        f"ниже норматива {steps(mask)} из {len(s)} шагов расчёта (≈{dur_hours(mask):g} ч)"))
                add_alert(rule_id, nid, v, "м вод.ст.", t, eid,
                          f"Давление в {nid} опускается до {v} м (ниже норматива ≈{dur_hours(mask):g} ч за сутки).",
                          duration_h=dur_hours(mask), deviation=round(lim - v, 2))
        lim = float(rules["high_pressure_warning"]["value"])
        mask = s > lim
        if mask.any():
            t = float(s[mask].idxmax()); v = round(float(s[t]), 2)
            eid = ev.add(obj=nid, metric="pressure", value=v, unit="м вод.ст.", time_h=t,
                         threshold_rule="high_pressure_warning",
                         statement=f"{nid}: давление {v} м вод.ст. в {t:g} ч превышает норматив {lim} м")
            add_alert("high_pressure_warning", nid, v, "м вод.ст.", t, eid,
                      f"Повышенное давление в {nid}: {v} м.", duration_h=dur_hours(mask), deviation=round(v - lim, 2))

    # --- скорости и обратные потоки
    for lid in res.wn.pipe_name_list:
        if lid not in ve.columns:
            continue
        s = ve[lid]
        for rule_id in ("high_velocity_critical", "high_velocity_warning"):
            lim = float(rules[rule_id]["value"])
            mask = s > lim
            if mask.any():
                t = float(s[mask].idxmax()); v = round(float(s[t]), 2)
                eid = ev.add(obj=lid, metric="velocity", value=v, unit="м/с", time_h=t,
                             threshold_rule=rule_id,
                             statement=(f"{lid}: скорость {v} м/с в {t:g} ч (норматив {lim} м/с), "
                                        f"{steps(mask)} из {len(s)} шагов расчёта (≈{dur_hours(mask):g} ч)"))
                add_alert(rule_id, lid, v, "м/с", t, eid,
                          f"Скорость в {lid} достигает {v} м/с.", duration_h=dur_hours(mask), deviation=round(v - lim, 2))
        f = fl[lid]
        if (f < -1e-6).any() and (f > 1e-6).any():
            t = float(f.idxmin()); v = round(float(f.min()), 2)
            eid = ev.add(obj=lid, metric="flowrate", value=v, unit="л/с", time_h=t,
                         threshold_rule="reverse_flow",
                         statement=f"{lid}: направление потока меняется в течение суток, минимум {v} л/с (обратный поток) в {t:g} ч")
            add_alert("reverse_flow", lid, v, "л/с", t, eid,
                      f"В {lid} поток меняет направление (переток/реверсирование).", duration_h=float((f < 0).sum()))
        if (st[lid] < 0.5).any():
            t = float(st[lid][st[lid] < 0.5].index[0])
            explicitly_closed = False
            try:
                explicitly_closed = str(res.wn.get_link(lid).initial_status).lower().endswith("closed")
            except Exception:  # noqa: BLE001
                pass
            if explicitly_closed:
                eid = ev.add(obj=lid, metric="status", value="closed", unit="-", time_h=t,
                             threshold_rule="pipe_closed",
                             statement=f"{lid}: участок закрыт с {t:g} ч — отключение задано в модели, расход по нему равен нулю")
                add_alert("pipe_closed", lid, "closed", "-", t, eid,
                          f"Участок {lid} отключён (задано в модели).", duration_h=dur_hours(st[lid] < 0.5))
            else:
                eid = ev.add(obj=lid, metric="status", value="flow_stopped", unit="-", time_h=t,
                             threshold_rule="pipe_flow_stopped",
                             statement=(f"{lid}: поток прекращён с {t:g} ч — участок перекрыт решателем "
                                        f"(типичная причина: опустошение резервуара или недопустимый режим по давлению)"))
                add_alert("pipe_flow_stopped", lid, "flow_stopped", "-", t, eid,
                          f"Поток по {lid} прекращён как следствие режима (проверить резервуар/давление).",
                          duration_h=dur_hours(st[lid] < 0.5))

    # --- недоподача (проявляется в PDA-режиме)
    try:
        exp = expected_demand_lps(res)
        deficit = demand_deficit_lps(res)
        for nid in res.junction_ids:
            exp_max = float(exp[nid].max())
            if exp_max <= 1e-9 or nid not in deficit.columns:
                continue
            dmax = float(deficit[nid].max())
            ratio = dmax / exp_max
            if ratio > 0.05:
                rule_id = "supply_deficit_critical" if ratio > 0.20 else "supply_deficit_warning"
                t = float(deficit[nid].idxmax())
                m_def = deficit[nid] > 0.05 * exp_max
                eid = ev.add(obj=nid, metric="demand_deficit", value=round(dmax, 2), unit="л/с", time_h=t,
                             threshold_rule=rule_id,
                             statement=(f"{nid}: подано на {dmax:.2f} л/с меньше расчётного спроса в {t:g} ч "
                                        f"({ratio * 100:.0f}% от требуемого, ≈{dur_hours(m_def):g} ч за сутки)"))
                add_alert(rule_id, nid, round(dmax, 2), "л/с", t, eid,
                          f"Недоподача в {nid}: до {dmax:.2f} л/с ({ratio * 100:.0f}% расчётного спроса).",
                          duration_h=dur_hours(m_def), deviation=round(dmax, 2))
    except Exception:  # noqa: BLE001
        pass

    # --- резервуары
    for tid in res.wn.tank_name_list:
        t_obj = res.wn.get_node(tid)
        s = pr[tid]
        for rule_id, delta in (("tank_at_min", 0.05), ("tank_near_min", 0.3)):
            lim = float(t_obj.min_level) + delta
            mask = s <= lim
            if mask.any():
                t = float(s[mask].idxmin()); v = round(float(s.min()), 2)
                eid = ev.add(obj=tid, metric="tank_level", value=v, unit="м", time_h=t,
                             threshold_rule=rule_id,
                             statement=(f"{tid}: уровень {v} м при минимально допустимом {float(t_obj.min_level):g} м; "
                                        f"у минимума ≈{dur_hours(mask):g} ч за сутки"))
                add_alert(rule_id, tid, v, "м", t, eid,
                          f"Запас в {tid} снижается до {v} м при минимуме {float(t_obj.min_level):g} м.",
                          duration_h=dur_hours(mask), deviation=round(lim - v, 2))
                break

    # --- насосы
    for pid in res.wn.pump_name_list:
        st_ = link_static(res.wn, pid)
        maxq = st_.get("max_curve_flow_lps")
        if not maxq or pid not in fl.columns:
            continue
        q = fl[pid].abs()
        lim = 1.15 * maxq
        mask = q > lim
        if mask.any():
            t = float(q.idxmax()); v = round(float(q.max()), 1)
            eid = ev.add(obj=pid, metric="pump_flow", value=v, unit="л/с", time_h=t,
                         threshold_rule="pump_beyond_curve",
                         statement=f"{pid}: расход {v} л/с превышает 1,15·Qmax характеристики ({round(maxq,1)} л/с)")
            add_alert("pump_beyond_curve", pid, v, "л/с", t, eid,
                      f"Насос {pid} работает за пределами характеристики ({v} л/с при Qmax {round(maxq,1)} л/с).",
                      duration_h=dur_hours(mask), deviation=round(v - lim, 1))

    # --- сходимость
    warns = res.scenario.get("result_ref", {}).get("solver_warnings", [])
    if warns or not res.scenario.get("result_ref", {}).get("converged", True):
        txt = "; ".join(warns) if warns else "расчёт не сошёлся"
        eid = ev.add(obj="network", metric="convergence", value="failed", unit="-", time_h=None,
                     threshold_rule="convergence_issue",
                     statement=f"Проблема сходимости расчёта: {txt}")
        alerts.append({"alert_id": f"A-{len(alerts) + 1:03d}", "rule": "convergence_issue",
                       "severity": "critical", "object": "network", "value": "failed", "unit": "-",
                       "time_h": None, "evidence_id": eid, "statement": f"Проблема сходимости: {txt}",
                       "duration_h": None})
    return alerts


def rank_problems(alerts: list[dict], ranking: dict, k: int = 12) -> list[dict]:
    """Ранжирует алерты в Top-K. Скоринг детерминированный и объяснимый."""
    sev_w = ranking["severity_weight"]
    scored = []
    for a in alerts:
        sev = sev_w.get(a["severity"], 0.5)
        dev = float(a.get("deviation") or 0.0)
        if a["unit"] in ("м вод.ст.", "м"):
            scale = 10.0
        elif a["unit"] == "м/с":
            scale = 1.0
        elif a["unit"] == "л/с":
            scale = 5.0
        else:
            scale = 10.0
        dev_norm = min(abs(dev) / scale, 3.0)
        dur_norm = min(float(a.get("duration_h") or 0.0) / 12.0, 2.0)
        score = sev * (1.0 + dev_norm + ranking["duration_weight"] * dur_norm)
        scored.append({**a, "score": round(score, 3)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:k]


# ─────────────────────────────────────────────────── сравнение сценариев

def compare(res_a: ScenarioResults, res_b: ScenarioResults, ev: EvidenceFactory | None = None,
            top: int = 10) -> dict:
    """Сравнение двух расчётов (A — база, B — сценарий). Возвращает локализованные изменения."""
    ev = ev or EvidenceFactory()
    out = {"a": res_a.scenario["scenario_id"], "b": res_b.scenario["scenario_id"], "items": []}
    common_nodes = [n for n in res_a.junction_ids if n in res_b.junction_ids]
    if not common_nodes:
        return out
    pa, pb = res_a.pressure[common_nodes], res_b.pressure[common_nodes]

    dp_mean = (pb - pa).mean(axis=0)
    dp_min = (pb.min(axis=0) - pa.min(axis=0))
    rows = []
    for n in common_nodes:
        rows.append({
            "object": n, "type": "junction",
            "delta_min_pressure_m": round(float(dp_min[n]), 2),
            "delta_mean_pressure_m": round(float(dp_mean[n]), 2),
            "p_min_a": round(float(pa[n].min()), 2), "p_min_b": round(float(pb[n].min()), 2),
        })
    rows.sort(key=lambda r: r["delta_min_pressure_m"])
    for r in rows[:top]:
        d = r["delta_min_pressure_m"]
        if abs(d) < 0.05:
            continue
        eid = ev.add(obj=r["object"], metric="delta_min_pressure", value=d, unit="м",
                     time_h=None, threshold_rule=None,
                     statement=f"{r['object']}: минимальное давление изменилось с {r['p_min_a']} до {r['p_min_b']} м ({'+' if d > 0 else ''}{d} м)")
        r["evidence_id"] = eid
        out["items"].append(r)

    # участки: изменение максимальной скорости и переток
    rows_l = []
    for lid in res_a.wn.pipe_name_list:
        if lid not in res_b.velocity.columns:
            continue
        va, vb = res_a.velocity[lid].max(), res_b.velocity[lid].max()
        fa, fb = res_a.flowrate[lid], res_b.flowrate[lid]
        rows_l.append({"object": lid, "type": "pipe", "v_max_a": round(float(va), 2), "v_max_b": round(float(vb), 2),
                       "delta_v_max_mps": round(float(vb - va), 2),
                       "flow_a_mean_lps": round(float(fa.mean()), 1), "flow_b_mean_lps": round(float(fb.mean()), 1),
                       "delta_flow_mean_lps": round(float(fb.mean() - fa.mean()), 1)})
    rows_l.sort(key=lambda r: -abs(r["delta_flow_mean_lps"]))
    for r in rows_l[:top]:
        if abs(r["delta_flow_mean_lps"]) < 1.0 and abs(r["delta_v_max_mps"]) < 0.1:
            continue
        eid = ev.add(obj=r["object"], metric="delta_flow", value=r["delta_flow_mean_lps"], unit="л/с",
                     time_h=None, threshold_rule=None,
                     statement=(f"{r['object']}: средний расход {r['flow_a_mean_lps']} → {r['flow_b_mean_lps']} л/с "
                                f"({'+' if r['delta_flow_mean_lps'] > 0 else ''}{r['delta_flow_mean_lps']} л/с), "
                                f"макс. скорость {r['v_max_a']} → {r['v_max_b']} м/с"))
        r["evidence_id"] = eid
        out["items"].append(r)

    out["summary"] = {
        "nodes_worse": int((dp_min < -0.5).sum()), "nodes_better": int((dp_min > 0.5).sum()),
        "worst_object": rows[0]["object"] if rows else None,
        "worst_delta_m": rows[0]["delta_min_pressure_m"] if rows else None,
    }
    return out


# ───────────────────────────────────────────────────────── сборка derived

def build_derived(scenario_dir: Path | str, thresholds_path: str = "configs/thresholds.yaml",
                  baseline_dir: Path | str | None = None) -> dict:
    """Считает derived_metrics.json и evidence.json для сценария."""
    res = load_results(scenario_dir)
    thresholds = common.load_yaml(thresholds_path)
    ev = EvidenceFactory()

    alerts = detect_alerts(res, thresholds, ev)
    top = rank_problems(alerts, thresholds["ranking"], k=common.load_yaml("configs/dataset.yaml")["context"]["max_alerts"])

    kpi = compute_kpis(res)
    kpi_refs = []
    for key, (obj, metric, val, unit) in {
        "min_pressure": (kpi["min_pressure_node"], "pressure", kpi["min_pressure_m"], "м вод.ст."),
        "max_pressure": (kpi["max_pressure_node"], "pressure", kpi["max_pressure_m"], "м вод.ст."),
        "max_velocity": (kpi["max_velocity_link"], "velocity", kpi["max_velocity_mps"], "м/с"),
    }.items():
        kpi_refs.append(ev.add(obj=obj, metric=metric, value=val, unit=unit, time_h=None, threshold_rule=None,
                               statement=f"Сводный KPI {key}: {obj} = {val} {unit}"))

    derived = {
        "scenario_id": res.scenario["scenario_id"],
        "network_id": res.scenario["network_id"],
        "analysis": {
            "type": "extended_period",
            "duration_h": int(res.time_h[-1] - res.time_h[0]),
            "step_h": float(res.time_h[1] - res.time_h[0]) if len(res.time_h) > 1 else None,
            "status": "converged" if res.scenario.get("result_ref", {}).get("converged", True) else "not_converged",
            "solver_warnings": res.scenario.get("result_ref", {}).get("solver_warnings", []),
            "units": {"pressure": "м вод.ст.", "flow": "л/с", "velocity": "м/с"},
        },
        "network_summary": network_summary(res.wn),
        "kpi": kpi,
        "kpi_evidence_refs": kpi_refs,
        "alerts": alerts,
        "top_problems": top,
        "node_table": [node_profile(res, n) for n in res.junction_ids],
        "link_table": [link_profile(res, l) for l in res.wn.pipe_name_list],
    }

    if baseline_dir is not None:
        try:
            base = load_results(baseline_dir)
            cmp_ = compare(base, res, ev, top=common.load_yaml("configs/dataset.yaml")["context"]["max_alerts"])
            derived["comparison_to_baseline"] = cmp_
            derived["baseline_scenario_id"] = base.scenario["scenario_id"]
            # наблюдаемость эффекта: видно ли отличие от базового расчёта в данных
            worst = abs(float(cmp_.get("summary", {}).get("worst_delta_m") or 0.0))
            n_worse = int(cmp_.get("summary", {}).get("nodes_worse") or 0)
            derived["observability"] = {
                "worst_delta_min_pressure_m": round(worst, 2),
                "nodes_worse": n_worse,
                "visible_effect": bool(worst >= 0.5 or n_worse >= 2),
                "note": ("эффект хорошо различим" if worst >= 2.0 else
                         "эффект слабый — внимательно проверьте, есть ли инженерная проблема"),
            }
        except Exception as e:  # noqa: BLE001
            derived["comparison_to_baseline"] = {"error": str(e)}
            derived["observability"] = {"visible_effect": None, "note": "нет базового расчёта для сравнения"}

    common.write_json(Path(scenario_dir) / "derived" / "derived_metrics.json", derived)
    common.write_json(Path(scenario_dir) / "derived" / "evidence.json", ev.items)
    return derived
