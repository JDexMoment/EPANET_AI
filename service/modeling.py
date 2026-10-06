"""Подготовка загруженной модели: прогон EPANET → аналитика → контексты для LLM.

Переиспользует боевой пайплайн проекта (src/generate/run_scenarios.run_one,
src/analytics.build_derived, src/context_builder.build_context), поэтому инженер в сервисе
видит ровно те же KPI, алерты, факты E-xxx и контекст, что увидит модель обучения.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import config

ROOT = config.ROOT


def scenario_id(model_id: str) -> str:
    """Каталог-«сценарий» для загруженной модели — как у штатных расчётов проекта."""
    return f"up_{model_id}"


def model_dir(model_id: str) -> Path:
    return config.MODELS / scenario_id(model_id)


def _network_summary(inp: Path) -> dict:
    import wntr
    wn = wntr.network.WaterNetworkModel(str(inp))
    return {
        "nodes": len(wn.node_name_list),
        "links": len(wn.link_name_list),
        "junctions": len(wn.junction_name_list),
        "tanks": len(wn.tank_name_list),
        "reservoirs": len(wn.reservoir_name_list),
        "pumps": len(wn.pump_name_list),
        "valves": len(wn.valve_name_list),
        "node_names": list(wn.node_name_list),
        "link_names": list(wn.link_name_list),
    }


def prepare(model_id: str, clean_inp: Path) -> dict:
    """Запускает расчёт и аналитику для загруженной модели. Возвращает сводку для UI."""
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from src import analytics, common, context_builder
    from src.generate import run_scenarios

    sdir = model_dir(model_id)          # service_data/models/up_<id>
    sdir.mkdir(parents=True, exist_ok=True)
    inp_local = sdir / "network.inp"
    if Path(clean_inp).resolve() != inp_local.resolve():
        shutil.copyfile(clean_inp, inp_local)

    summary = _network_summary(inp_local)

    if not config.RUN_SIMULATION:
        return {"simulated": False, "network": summary,
                "note": "расчёт отключён (RUN_SIMULATION=0): разметка доступна без KPI и фактов"}

    # переиспользуем прогон сценария без правок: та же сетка, те же CSV, тот же формат
    run_res = run_scenarios.run_one(
        base_inp=inp_local, scenario_id=scenario_id(model_id), network_id=f"uploaded:{model_id}",
        edits=[], truth={"source": "uploaded_model", "is_faulted": None},
        out_root=config.MODELS, baseline_ref=None, seed=0, demand_jitter_pct=0.0,
    )
    if run_res.get("status") != "ok":
        return {"simulated": False, "network": summary,
                "error": f"расчёт EPANET не выполнен: {run_res.get('error')}"}

    derived = analytics.build_derived(sdir, baseline_dir=None)
    contexts = []
    for mode in config.CONTEXT_MODES:
        try:
            ctx = context_builder.build_context(sdir, mode=mode)
            common.write_json(sdir / "derived" / f"llm_context_{mode}.json", ctx)
            contexts.append({"mode": mode, "chars": ctx["_meta"]["chars"],
                             "evidence": ctx["_meta"]["evidence_count"],
                             "truncated": ctx["_meta"]["truncated"]})
        except Exception as e:  # noqa: BLE001
            contexts.append({"mode": mode, "error": f"{type(e).__name__}: {e}"})

    warnings = list((derived.get("analysis") or {}).get("solver_warnings") or [])
    warnings += list(((common.read_json(sdir / "scenario.json").get("result_ref") or {})
                      .get("result_notes") or []))

    return {
        "simulated": True,
        "scenario_id": scenario_id(model_id),
        "dir": str(sdir),
        "network": summary,
        "kpi": derived["kpi"],
        "alerts": derived["alerts"],
        "top_problems": derived["top_problems"],
        "objects": _objects_table(derived),
        "evidence": common.read_json(sdir / "derived" / "evidence.json"),
        "analysis": derived.get("analysis"),
        "observability": derived.get("observability"),
        "contexts": contexts,
        "warnings": warnings,
    }


def _objects_table(derived: dict) -> list[dict]:
    """Плоская таблица объектов: то, что инженер видит списком и может выбрать."""
    rows: list[dict] = []
    ev_by_key: dict[tuple, str] = {}
    for a in derived.get("alerts", []):
        ev_by_key.setdefault((a.get("object"), a.get("rule")), a.get("evidence_id"))
    for n in derived.get("node_table", []):
        p = n.get("pressure", {}) or {}
        d = n.get("demand", {}) or {}
        rows.append({
            "id": n["id"], "type": n.get("type", "junction"),
            "p_min": p.get("min"), "p_min_at_h": p.get("t_min_h"),
            "p_max": p.get("max"), "demand_mean_lps": d.get("mean"),
            "elev_m": n.get("elevation_m"),
            "evidence_id": ev_by_key.get((n["id"], "low_pressure_warning"))
                           or ev_by_key.get((n["id"], "low_pressure_critical")),
        })
    for l in derived.get("link_table", []):
        v = l.get("velocity", {}) or {}
        q = l.get("flow", {}) or {}
        rows.append({
            "id": l["id"], "type": l.get("type", "pipe"),
            "from": l.get("from"), "to": l.get("to"), "diam_mm": l.get("diameter_mm"),
            "length_m": l.get("length_m"), "roughness_c": l.get("roughness_c"),
            "v_max_mps": v.get("max"), "q_mean_lps": q.get("mean"),
            "status": l.get("status"),
        })
    return rows


def context_text_for(model_id: str, mode: str) -> str:
    """Текст контекста, который видел инженер: сначала нужный режим, потом любой доступный.

    Нужен для самопроверки ответа: числа из контекста (нормативы, KPI) считаются законными.
    """
    import json
    d = model_dir(model_id) / "derived"
    for cand in (d / f"llm_context_{mode}.json",
                 d / "llm_context_whats_happening.json",
                 *sorted(d.glob("llm_context_*.json"))):
        if cand.exists():
            return cand.read_text(encoding="utf-8")
    # нормативы из thresholds.yaml тоже законно цитировать
    try:
        import yaml
        th = yaml.safe_load((ROOT / "configs" / "thresholds.yaml").read_text(encoding="utf-8"))
        return json.dumps([r.get("value") for r in th.get("rules", [])], ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return ""


def read_context(model_id: str, mode: str) -> dict | None:
    import json
    for cand in (model_dir(model_id) / "derived" / f"llm_context_{mode}.json",):
        if cand.exists():
            return json.loads(cand.read_text(encoding="utf-8"))
    return None


def read_derived(model_id: str) -> dict | None:
    import json
    p = model_dir(model_id) / "derived" / "derived_metrics.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
