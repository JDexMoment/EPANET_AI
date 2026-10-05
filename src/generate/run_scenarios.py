"""Генератор сценариев расчёта EPANET.

Сценарий = сеть + правки (неисправности) + результаты расчёта.
Это «сырьё» датасета: инженеры размечают кейсы, построенные на сценариях.

Запуск:
    python -m src.generate.run_scenarios --network vn01 --count 24
    python -m src.generate.run_scenarios --network vn01 --baseline
"""
from __future__ import annotations

import argparse
import traceback
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import wntr
from wntr.network import LinkStatus

from .. import common, analytics

warnings.filterwarnings("ignore")

NETWORKS = {
    "vn01": "data/raw/sample_net_01.inp",
}

# диапазоны величины неисправности (ground truth)
FAULT_SPECS = {
    "pipe_roughness_drop": {
        "targets": "pipes", "range": (0.35, 0.75), "step": 0.05,
        "label": "pipe_incrustation", "severity": "warning",
        "expected_effect": "рост потерь напора на участке, снижение давления за участком",
    },
    "pipe_roughness_gain": {
        "targets": "pipes", "range": (1.30, 1.60), "step": 0.05,
        "label": "pipe_incrustation", "severity": "info",
        "expected_effect": "заниженные потери напора (возможна ошибка модели), давление выше ожидаемого",
    },
    "pipe_closed": {
        "targets": "pipes", "range": (1.0, 1.0), "step": 0.0,
        "label": "pipe_closed_section", "severity": "critical",
        "expected_effect": "перераспределение потоков, рост скоростей на обходных участках",
    },
    "demand_increase": {
        "targets": "junctions", "range": (1.5, 4.0), "step": 0.25,
        "label": "demand_anomaly", "severity": "warning",
        "expected_effect": "рост расхода и снижение давления в локальной зоне",
    },
    "pump_degradation": {
        "targets": "pumps", "range": (0.70, 0.90), "step": 0.05,
        "label": "pump_degradation", "severity": "warning",
        "expected_effect": "снижение напора насоса, падение давления по всей зоне подачи",
    },
    "tank_level_low": {
        "targets": "tanks", "range": (1.0, 1.0), "step": 0.0,
        "label": "tank_level_deficit", "severity": "warning",
        "expected_effect": "потеря регулирующего запаса, рост зависимости от насосной станции",
    },
}


# ─────────────────────────────────────────── правки модели (edits)

def _pick_target(wn, spec, rnd: np.random.Generator) -> str:
    kind = spec["targets"]
    if kind == "pipes":
        return str(rnd.choice(wn.pipe_name_list))
    if kind == "junctions":
        dem = np.array([float(wn.get_node(n).demand_timeseries_list[0].base_value)
                        for n in wn.junction_name_list]) + 1e-6
        p = dem / dem.sum()
        return str(rnd.choice(wn.junction_name_list, p=p))
    if kind == "pumps":
        return str(rnd.choice(wn.pump_name_list))
    if kind == "tanks":
        return str(rnd.choice(wn.tank_name_list))
    raise ValueError(kind)


def _apply_edit(wn, fault: str, target: str, magnitude: float) -> dict:
    """Применяет неисправность к модели. magnitude: масштаб (см. FAULT_SPECS)."""
    if fault == "pipe_roughness_drop":
        l = wn.get_link(target)
        before = float(l.roughness)
        l.roughness = before * magnitude
        return {"op": "set_roughness", "target": target, "value": round(float(l.roughness), 1),
                "note": f"C: {before:.0f} → {l.roughness:.1f} (зарастание, масштаб {magnitude})"}
    if fault == "pipe_roughness_gain":
        l = wn.get_link(target)
        before = float(l.roughness)
        l.roughness = before * magnitude
        return {"op": "set_roughness", "target": target, "value": round(float(l.roughness), 1),
                "note": f"C: {before:.0f} → {l.roughness:.1f} (аномально низкое сопротивление)"}
    if fault == "pipe_closed":
        l = wn.get_link(target)
        l.initial_status = LinkStatus.Closed
        return {"op": "set_status", "target": target, "value": "closed", "note": "участок отключён"}
    if fault == "demand_increase":
        n = wn.get_node(target)
        d = n.demand_timeseries_list[0]
        before = float(d.base_value)
        d.base_value = before * magnitude
        return {"op": "scale_demand", "target": target, "value": round(float(d.base_value) * 1000, 3),
                "note": f"спрос {before * 1000:.2f} → {float(d.base_value) * 1000:.2f} л/с (x{magnitude})"}
    if fault == "pump_degradation":
        p = wn.get_link(target)
        cname = p.pump_curve_name
        curve = wn.get_curve(cname)
        new_points = [(float(x), float(y) * magnitude) for x, y in curve.points]
        p.pump_curve_name = None
        wn.remove_curve(cname)
        wn.add_curve(cname, "HEAD", new_points)
        p.pump_curve_name = cname
        return {"op": "set_pump_curve_scale", "target": target, "value": magnitude,
                "note": f"характеристика насоса снижена на {(1 - magnitude) * 100:.0f}%"}
    if fault == "tank_level_low":
        t = wn.get_node(target)
        before = float(t.init_level)
        t.init_level = float(t.min_level)
        return {"op": "set_tank_init_level", "target": target, "value": float(t.init_level),
                "note": f"начальный уровень {before:.1f} → {t.init_level:.1f} м (запас отсутствует)"}
    raise ValueError(fault)


# ───────────────────────────────────────────────────── прогон сценария

def run_one(base_inp: Path, scenario_id: str, network_id: str, edits: list[tuple[str, str, float]],
            truth: dict, out_root: Path, baseline_ref: str | None, seed: int,
            demand_jitter_pct: float = 0.0) -> dict:
    wn = wntr.network.WaterNetworkModel(str(base_inp))

    # режим расчёта: PDA даёт физичную недоподачу вместо отрицательных давлений
    epa = common.load_yaml("configs/dataset.yaml").get("epanet", {})
    if str(epa.get("demand_model", "DDA")).upper() == "PDA":
        wn.options.hydraulic.demand_model = "PDA"
        wn.options.hydraulic.required_pressure = float(epa.get("required_pressure_m", 20.0))
        wn.options.hydraulic.minimum_pressure = float(epa.get("minimum_pressure_m", 0.0))
        wn.options.hydraulic.pressure_exponent = float(epa.get("pressure_exponent", 0.5))

    # небольшой разброс базового спроса — чтобы кейсы не были идентичными
    if demand_jitter_pct:
        rnd = np.random.default_rng(seed)
        for nid in wn.junction_name_list:
            d = wn.get_node(nid).demand_timeseries_list[0]
            d.base_value = float(d.base_value) * (1.0 + rnd.normal(0, demand_jitter_pct / 100.0))

    applied, solver_warnings = [], []
    for fault, target, mag in edits:
        try:
            applied.append(_apply_edit(wn, fault, target, mag))
        except Exception as e:  # noqa: BLE001
            solver_warnings.append(f"edit_failed:{fault}:{target}:{e}")

    sdir = common.ensure_dir(out_root / scenario_id)
    inp_path = sdir / "network.inp"
    wntr.network.io.write_inpfile(wn, str(inp_path))

    t0 = pd.Timestamp.utcnow()
    converged = True
    try:
        sim = wntr.sim.EpanetSimulator(wn)
        res = sim.run_sim()
    except Exception as e:  # noqa: BLE001
        common.write_json(sdir / "scenario.json", {
            "scenario_id": scenario_id, "network_id": network_id, "created": common.now_iso(),
            "seed": seed, "base_inp": str(base_inp), "scenario_inp": str(inp_path),
            "edits": applied, "truth": {**truth, "is_faulted": bool(edits)},
            "result_ref": {"dir": str(sdir), "converged": False, "solver_warnings": [f"exception:{e}"]},
        })
        return {"scenario_id": scenario_id, "status": "failed", "error": str(e)}

    dur = (pd.Timestamp.utcnow() - t0).total_seconds()

    pressure = res.node["pressure"].copy(); pressure.index = pressure.index / 3600.0
    head = res.node["head"].copy(); head.index = head.index / 3600.0
    demand = res.node["demand"].copy(); demand.index = demand.index / 3600.0
    flow = res.link["flowrate"].copy(); flow.index = flow.index / 3600.0
    vel = res.link["velocity"].copy(); vel.index = vel.index / 3600.0
    status = res.link["status"].copy(); status.index = status.index / 3600.0

    na_cells = int(pressure.isna().sum().sum())
    if na_cells:
        converged = False
        solver_warnings.append(f"NaN в результатах: {na_cells} ячеек (расчёт не сошёлся в части шагов)")
    neg_press = int((pressure[[n for n in wn.junction_name_list]] < -5).sum().sum())
    if neg_press:
        solver_warnings.append(f"отрицательное давление (< -5 м) в {neg_press} точках — режим физически недостижим")
    # закрытые участки — не ошибка решателя, а следствие режима: пишем отдельной заметкой
    notes = []
    if (status < 0.5).any().any():
        notes.append("в результатах есть закрытые участки (см. алерты pipe_closed / pipe_flow_stopped)")

    out = common.ensure_dir(sdir / "results")
    pressure.round(4).to_csv(out / "pressure.csv")
    head.round(4).to_csv(out / "head.csv")
    demand.round(8).to_csv(out / "demand.csv")
    flow.round(8).to_csv(out / "flowrate.csv")
    vel.round(5).to_csv(out / "velocity.csv")
    status.round(0).astype(int).to_csv(out / "link_status.csv")

    scen = {
        "scenario_id": scenario_id, "network_id": network_id, "created": common.now_iso(),
        "seed": seed, "base_inp": str(base_inp.relative_to(common.ROOT)) if str(base_inp).startswith(str(common.ROOT)) else str(base_inp),
        "scenario_inp": str(inp_path.relative_to(common.ROOT)),
        "baseline_ref": baseline_ref,
        "edits": applied,
        "truth": {**truth, "is_faulted": bool(edits)},
        "result_ref": {"dir": str(sdir.relative_to(common.ROOT)), "converged": converged,
                       "solver_warnings": solver_warnings, "result_notes": notes,
                       "runtime_s": round(dur, 2)},
    }
    common.write_json(sdir / "scenario.json", scen)
    return {"scenario_id": scenario_id, "status": "ok", "converged": converged,
            "n_alerts_preview": None, "dir": str(sdir)}


# ──────────────────────────────────────────────────────── планирование

def build_queue(cfg: dict, network_id: str, count: int, seed: int) -> list[dict]:
    base = common.ROOT / NETWORKS[network_id]
    wn = wntr.network.WaterNetworkModel(str(base))
    rnd = np.random.default_rng(seed)
    mix = cfg["generation"]["fault_mix"]
    kinds = list(mix.keys()); weights = np.array([mix[k] for k in kinds], dtype=float); weights /= weights.sum()

    queue = []
    used = set()
    for i in range(count):
        for _ in range(50):
            fault = str(rnd.choice(kinds, p=weights))
            spec = FAULT_SPECS[fault]
            target = _pick_target(wn, spec, rnd)
            lo, hi = spec["range"]; step = spec["step"]
            mag = round(float(rnd.uniform(lo, hi)) / step) * step if step else lo
            mag = round(mag, 2)
            key = (fault, target, mag)
            if key not in used:
                used.add(key)
                break
        sid = f"{network_id}__{fault}__{target.replace('-', '')}__{int(mag * 100):03d}"
        truth = {
            "is_faulted": True, "primary_fault": spec["label"],
            "fault_severity": spec["severity"],
            "expected_effects": [spec["expected_effect"]],
            "difficulty": "easy" if fault in ("pipe_closed", "tank_level_low") else "medium",
            "notes_for_expert": f"В модель внесено: {fault} на {target}, масштаб {mag}. "
                                f"Инженер должен подтвердить/уточнить наблюдаемые последствия и метку.",
        }
        queue.append({"scenario_id": sid, "network_id": network_id, "edits": [(fault, target, mag)],
                      "truth": truth, "seed": int(seed + i)})
    return queue


def main() -> None:
    ap = argparse.ArgumentParser(description="Генерация сценариев EPANET")
    ap.add_argument("--network", default="vn01", choices=list(NETWORKS.keys()))
    ap.add_argument("--count", type=int, default=24)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--baseline", action="store_true", help="только baseline-сценарий")
    ap.add_argument("--out", default="data/scenarios")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/dataset.yaml")
    seed = args.seed if args.seed is not None else cfg["generation"]["seed"]
    out_root = common.ROOT / args.out
    base = common.ROOT / NETWORKS[args.network]

    manifest_path = out_root / "manifest.jsonl"
    manifest = common.read_jsonl(manifest_path) if manifest_path.exists() else []
    done = {m["scenario_id"] for m in manifest}

    # baseline
    base_id = f"{args.network}__baseline"
    if base_id not in done:
        rec = run_one(base, base_id, args.network, [], {"is_faulted": False, "primary_fault": None,
                                                        "fault_severity": None, "expected_effects": ["базовый суточный режим без неисправностей"],
                                                        "difficulty": "easy", "notes_for_expert": "Опорный сценарий сети."},
                      out_root, None, seed, cfg["generation"]["demands_jitter_pct"])
        manifest.append(rec); done.add(base_id)
        print(f"[baseline] {base_id}: {rec['status']}, converged={rec.get('converged')}")

    if args.baseline:
        common.write_jsonl(manifest_path, manifest)
        return

    queue = build_queue(cfg, args.network, args.count, seed)
    baseline_dir = f"data/scenarios/{base_id}"

    for i, item in enumerate(queue, 1):
        if item["scenario_id"] in done:
            continue
        try:
            rec = run_one(base, item["scenario_id"], item["network_id"], item["edits"], item["truth"],
                          out_root, baseline_dir, item["seed"], cfg["generation"]["demands_jitter_pct"])
        except Exception as e:  # noqa: BLE001
            rec = {"scenario_id": item["scenario_id"], "status": "failed", "error": str(e)}
            traceback.print_exc()
        manifest.append(rec); done.add(item["scenario_id"])
        print(f"[{i}/{len(queue)}] {item['scenario_id']}: {rec['status']}")

    common.write_jsonl(manifest_path, manifest)
    print(f"\nВсего сценариев в манифесте: {len(manifest)} → {manifest_path}")


if __name__ == "__main__":
    main()
