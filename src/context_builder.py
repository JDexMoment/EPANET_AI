"""Context Builder: собирает компактный машиночитаемый контекст для LLM.

Принципы (roadmap п.5, п.10):
  * модель получает НЕ весь INP и НЕ весь CSV, а сжатый JSON;
  * все числа уже посчитаны Analytics Engine и помечены ссылками E-xxx;
  * бюджет контекста ограничен (max_context_chars), усечение детерминированное.

Этот же модуль используется:
  * в inference (реальный запрос пользователя);
  * при построении датасета (инженеры видят ровно тот же контекст, что увидит модель).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import analytics, common

MODE_TITLES = {
    "whats_happening": "Что происходит?",
    "explain_object": "Объяснить объект",
    "find_problems": "Найти проблемы",
    "why_happened": "Почему это произошло?",
    "make_report": "Составить отчёт",
    "compare_scenarios": "Сравнить сценарии",
    "ask": "Ответить на вопрос",
}


def _reduced_series(series: dict, max_points: int) -> dict:
    """Прореживает временной ряд до max_points точек, сохраняя минимум/максимум."""
    arr = series.get("values")
    if not arr or len(arr) <= max_points:
        return series
    import numpy as np
    a = np.asarray(arr, dtype=float)
    idx = np.unique(np.linspace(0, len(a) - 1, max_points).round().astype(int))
    keep = set(idx.tolist()) | {int(a.argmin()), int(a.argmax())}
    idx = np.array(sorted(keep))
    return {"time_h": [series["time_h"][i] for i in idx], "values": [round(float(a[i]), 2) for i in idx],
            "unit": series.get("unit"), "reduced": True}


def build_context(scenario_dir: Path | str, mode: str = "whats_happening",
                  question: str | None = None, selection: dict | None = None,
                  ui: dict | None = None, cfg: dict | None = None) -> dict:
    scenario_dir = Path(scenario_dir)
    if not scenario_dir.is_absolute():
        scenario_dir = common.ROOT / scenario_dir
    cfg = cfg or common.load_yaml("configs/dataset.yaml")
    ctx_cfg = cfg["context"]

    scenario = common.read_json(scenario_dir / "scenario.json")
    derived = common.read_json(scenario_dir / "derived" / "derived_metrics.json")
    evidence_all = common.read_json(scenario_dir / "derived" / "evidence.json")
    thresholds = common.load_yaml("configs/thresholds.yaml")

    res = analytics.load_results(scenario_dir)
    selection = selection or {"type": "whole_network", "id": None}

    used_evidence: set[str] = set(derived.get("kpi_evidence_refs", []))   # числа сводки тоже опираются на факты
    top_problems = derived["top_problems"][: ctx_cfg["max_alerts"]]

    ctx: dict = {
        "context_version": "1.0",
        "scenario": {
            "id": scenario["scenario_id"],
            "network": scenario["network_id"],
            "baseline_id": scenario.get("baseline_ref"),
        },
        "request": {
            "mode": mode,
            "mode_title": MODE_TITLES.get(mode, mode),
            "question": question or MODE_TITLES.get(mode, ""),
            "selection": selection,
            "ui": ui or {},
        },
        "analysis": derived["analysis"],
        "network_summary": derived["network_summary"],
        "kpi": derived["kpi"],
        "thresholds": [
            {"rule": r["id"], "condition": f"{r['metric']} {r['op']} {r.get('value', '')}".strip(),
             "severity": r["severity"], "meaning": r["text"]}
            for r in thresholds["rules"]
        ],
        "alerts": [],
        "objects_table": [],
    }

    for a in top_problems:
        a = dict(a)
        used_evidence.add(a["evidence_id"])
        ctx["alerts"].append({
            "rank": len(ctx["alerts"]) + 1,
            "rule": a["rule"], "severity": a["severity"], "object": a["object"],
            "value": a["value"], "unit": a["unit"], "time_h": a["time_h"],
            "duration_h": a.get("duration_h"), "evidence_id": a["evidence_id"],
        })

    # объект в фокусе (выделен пользователем)
    focus_id = selection.get("id")
    if focus_id and (focus_id in res.wn.node_name_list or focus_id in res.wn.link_name_list):
        prof = analytics.object_profile(res, focus_id)
        ctx["focus"] = {"object": prof, "neighbors": analytics.neighbors(res.wn, focus_id, ctx_cfg["neighbor_depth"])}
        # локальный временной ряд
        if focus_id in res.wn.node_name_list:
            series = {"time_h": [round(float(t), 1) for t in res.time_h],
                      "values": [round(float(v), 2) for v in res.pressure[focus_id].values], "unit": "м вод.ст."}
            ctx["focus"]["series_pressure"] = _reduced_series(series, ctx_cfg["max_series_points"])
            if focus_id in res.demand.columns:
                series_d = {"time_h": [round(float(t), 1) for t in res.time_h],
                            "values": [round(float(v), 2) for v in res.demand[focus_id].values], "unit": "л/с"}
                ctx["focus"]["series_demand"] = _reduced_series(series_d, ctx_cfg["max_series_points"])
        else:
            series = {"time_h": [round(float(t), 1) for t in res.time_h],
                      "values": [round(float(v), 2) for v in res.flowrate[focus_id].values], "unit": "л/с"}
            ctx["focus"]["series_flow"] = _reduced_series(series, ctx_cfg["max_series_points"])
        # ближайшие алерты по этому объекту
        local = [a for a in derived["alerts"] if a["object"] == focus_id][:5]
        for a in local:
            used_evidence.add(a["evidence_id"])
        ctx["focus"]["local_alerts"] = [{"rule": a["rule"], "severity": a["severity"], "value": a["value"],
                                         "unit": a["unit"], "time_h": a["time_h"], "evidence_id": a["evidence_id"]}
                                        for a in local]

    # компактная таблица объектов
    n_max = ctx_cfg["max_objects_in_table"]
    nodes = sorted(derived["node_table"], key=lambda n: n.get("pressure", {}).get("min", 1e9))[:n_max]
    for n in nodes:
        ctx["objects_table"].append({
            "id": n["id"], "type": n["type"], "elev_m": n.get("elevation_m"),
            "p_min": n.get("pressure", {}).get("min"), "p_max": n.get("pressure", {}).get("max"),
            "p_min_at_h": n.get("pressure", {}).get("t_min_h"),
            "demand_mean_lps": n.get("demand", {}).get("mean"),
        })
    if mode in ("make_report", "find_problems"):
        links = sorted(derived["link_table"], key=lambda l: -(l.get("velocity", {}).get("max") or 0))[:n_max]
        for l in links:
            ctx["objects_table"].append({
                "id": l["id"], "type": l["type"], "from": l.get("from"), "to": l.get("to"),
                "length_m": l.get("length_m"), "diam_mm": l.get("diameter_mm"), "roughness_c": l.get("roughness_c"),
                "v_max_mps": l.get("velocity", {}).get("max"), "q_mean_lps": l.get("flow", {}).get("mean"),
                "status": l.get("status"),
            })

    # сравнение с базовым расчётом (для «что изменилось» и «сравнить сценарии»)
    cmp_ = derived.get("comparison_to_baseline", {})
    if cmp_ and "items" in cmp_:
        ctx["baseline_delta"] = {
            "baseline_scenario_id": derived.get("baseline_scenario_id"),
            "summary": cmp_.get("summary"),
            "items": [],
        }
        for it in cmp_["items"][: ctx_cfg["max_alerts"]]:
            if "evidence_id" in it:
                used_evidence.add(it["evidence_id"])
            ctx["baseline_delta"]["items"].append(it)

    # evidence: только то, на что уже ссылаемся
    ctx["evidence"] = {eid: evidence_all[eid] for eid in sorted(used_evidence) if eid in evidence_all}

    # ── усечение под бюджет (детерминированное, с защитой от зацикливания)
    def size(o) -> int:
        return len(json.dumps(o, ensure_ascii=False))

    limit = ctx_cfg["max_context_chars"]
    # блок «что на экране» входит в тот же запрос — резервируем место под него
    ui_size = size(ctx.get("request", {}).get("ui") or {})
    target = max(2000, limit - ui_size)
    for _ in range(24):
        if size(ctx) <= target:
            break
        if len(ctx["objects_table"]) > 0:
            ctx["objects_table"] = ctx["objects_table"][: max(0, len(ctx["objects_table"]) // 2)]
        elif len(ctx["alerts"]) > 4:
            ctx["alerts"] = ctx["alerts"][:-1]
        elif ctx.get("baseline_delta", {}).get("items"):
            items = ctx["baseline_delta"]["items"]
            ctx["baseline_delta"]["items"] = items[: max(0, len(items) // 2)]
        elif len(ctx.get("focus", {}).get("neighbors") or []) > 5:
            nb = ctx["focus"]["neighbors"]
            ctx["focus"]["neighbors"] = nb[: max(2, len(nb) // 2)]
        elif any(isinstance(ctx.get("focus", {}).get(k), dict)
                 and len(ctx["focus"][k].get("values") or []) > 6
                 for k in ("series_pressure", "series_demand", "series_flow")):
            for k in ("series_pressure", "series_demand", "series_flow"):
                s = ctx.get("focus", {}).get(k)
                if isinstance(s, dict) and s.get("values") and len(s["values"]) > 6:
                    keep = max(6, len(s["values"]) // 2)
                    s["values"], s["time_h"], s["reduced"] = s["values"][:keep], s["time_h"][:keep], True
        elif len(ctx.get("thresholds", [])) > 6:
            ctx["thresholds"] = ctx["thresholds"][:6]
        elif len(ctx.get("evidence", {})) > 10:
            ctx["evidence"] = {k: ctx["evidence"][k] for k in sorted(ctx["evidence"])[:10]}
        else:
            break

    # жёсткий резерв: если сокращать больше нечего, а бюджет всё ещё превышен,
    # уменьшаем формулировки фактов и оставляем только самые важные из них
    if size(ctx) > target:
        for keep_n in (10, 8, 6, 4):
            if size(ctx) <= target:
                break
            ev = ctx.get("evidence") or {}
            if len(ev) > keep_n:
                ctx["evidence"] = {k: ev[k] for k in sorted(ev)[:keep_n]}
        for e in (ctx.get("evidence") or {}).values():
            if isinstance(e.get("statement"), str) and len(e["statement"]) > 140:
                e["statement"] = e["statement"][:137] + "..."

    ctx["_meta"] = {"chars": size(ctx), "evidence_count": len(ctx["evidence"]),
                    "truncated": size(ctx) > limit, "budget_chars": limit}
    return ctx


def render_for_prompt(ctx: dict) -> str:
    """JSON-представление контекста для вставки в промпт (компактное, без отступов)."""
    return json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))


def main() -> None:  # pragma: no cover - CLI для отладки
    import argparse
    ap = argparse.ArgumentParser(description="Сборка llm_context.json для сценария")
    ap.add_argument("scenario_dir")
    ap.add_argument("--mode", default="whats_happening", choices=list(MODE_TITLES))
    ap.add_argument("--object", default=None)
    ap.add_argument("--question", default=None)
    args = ap.parse_args()
    selection = {"type": "whole_network", "id": None}
    if args.object:
        sel_type = "junction" if args.object.startswith("J") else "pipe"
        selection = {"type": sel_type, "id": args.object}
    ctx = build_context(args.scenario_dir, mode=args.mode, question=args.question, selection=selection)
    out = Path(args.scenario_dir) / "derived" / f"llm_context_{args.mode}.json"
    common.write_json(out, ctx)
    print(f"OK → {out} ({ctx['_meta']['chars']} символов)")


if __name__ == "__main__":
    main()
