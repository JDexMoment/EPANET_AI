"""Распределяет СЦЕНАРИИ (а не отдельные кейсы!) по партиям для инженеров.

Правило: все кейсы одного сценария уходят одному инженеру — иначе разметка
одной ситуации противоречила бы сама себе.

Часть сценариев (double_annotation_every) уходит обоим экспертам — это
контроль качества (inter-annotator agreement), см. check_quality.py.

Запуск:
    python -m src.dataset.make_batches
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from .. import common


def main() -> None:
    ap = argparse.ArgumentParser(description="Партии для инженеров")
    ap.add_argument("--cases-dir", default="data/cases/pending")
    ap.add_argument("--out-dir", default="data/batches")
    ap.add_argument("--include-baseline", action="store_true", default=True)
    args = ap.parse_args()

    cfg = common.load_yaml("configs/experts.yaml")
    experts = [e["id"] for e in cfg["experts"]]
    every = int(cfg["review"]["double_annotation_every"])
    per_batch = int(cfg["load"]["scenarios_per_batch"])

    cases_dir = common.ROOT / args.cases_dir
    by_scenario: dict[str, list[str]] = defaultdict(list)
    for fp in sorted(cases_dir.glob("c_*.json")):
        case = common.read_json(fp)
        by_scenario[case["scenario_id"]].append(case["case_id"])

    scenarios = sorted(by_scenario.keys())
    assignment: dict[str, list[str]] = {}   # scenario_id → [expert_id, ...]
    for i, sid in enumerate(scenarios):
        primary = experts[i % len(experts)]
        owners = [primary]
        if i % every == every - 1:          # двойная разметка
            owners.append(experts[(i + 1) % len(experts)])
        assignment[sid] = owners

    # партии: режем по числу сценариев на инженера
    out_dir = common.ensure_dir(common.ROOT / args.out_dir)
    for exp in experts:
        own = [s for s in scenarios if exp in assignment[s]]
        for b_idx in range(0, len(own), per_batch):
            batch_scen = own[b_idx:b_idx + per_batch]
            case_ids = [c for s in batch_scen for c in by_scenario[s]]
            batch = {
                "batch_id": f"batch_{exp}_{b_idx // per_batch + 1:02d}",
                "expert_id": exp,
                "created": common.now_iso(),
                "scenario_ids": batch_scen,
                "case_ids": case_ids,
                "double_annotation": {s: assignment[s] for s in batch_scen if len(assignment[s]) > 1},
                "instructions_ref": "docs/06_ENGINEER_TASKS.md",
                "status": "open",
            }
            common.write_json(out_dir / f"{batch['batch_id']}.json", batch)
            print(f"{batch['batch_id']}: {len(batch_scen)} сценариев, {len(case_ids)} кейсов")

    common.write_json(out_dir / "assignments.json", {s: assignment[s] for s in scenarios})
    print(f"\nНазначения → {out_dir}/assignments.json")


if __name__ == "__main__":
    main()
