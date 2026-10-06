"""Собирает самодостаточную HTML-форму для инженера-эксперта.

Форма содержит ровно тот контекст, который увидит модель, плюс поля разметки
и эталонных ответов. Работает офлайн, экспорт — JSON, совместимый с schemas/case.schema.json.

Запуск:
    python -m src.dataset.make_expert_pack --batch data/batches/batch_exp_01_01.json
    python -m src.dataset.make_expert_pack --all
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import common

TEMPLATE = Path(__file__).parent / "expert_pack_template.html"


def _short_title(scen: dict, idx: int) -> str:
    """Нейтральный заголовок: НИЧЕГО не говорит о внесённой неисправности.

    Слепая разметка обязательна: инженер не должен знать ground truth,
    пока не заполнит разметку и не нажмёт «Показать, что внесено в модель».
    """
    return f"Сценарий {idx} · сеть {scen['network_id']} · суточный расчёт"


def build_pack(batch_fp: Path) -> Path:
    cfg = common.load_yaml("configs/dataset.yaml")
    batch = common.read_json(batch_fp)
    labels = common.load_yaml("configs/labels.yaml")

    categories = labels["categories"]
    severities = labels["severity"]
    confidence = labels["confidence"]
    check_actions = labels["verification_actions"]

    scenarios = []
    for idx, sid in enumerate(batch["scenario_ids"], 1):
        sdir = common.ROOT / PATHS["scenarios"] / sid
        scen = common.read_json(sdir / "scenario.json")
        derived = common.read_json(sdir / "derived" / "derived_metrics.json")
        evidence_all = common.read_json(sdir / "derived" / "evidence.json")

        # кейсы этого сценария из партии
        cases = []
        for cid in batch["case_ids"]:
            fp = common.ROOT / PATHS["pending"] / f"{cid}.json"
            if fp.exists():
                c = common.read_json(fp)
                if c["scenario_id"] == sid:
                    cases.append({"case_id": c["case_id"], "mode": c["mode"], "question": c["question"]})

        ctx_fp = sdir / "derived" / "llm_context_whats_happening.json"
        ctx_json = ctx_fp.read_text(encoding="utf-8") if ctx_fp.exists() else "{}"

        refs = [a["evidence_id"] for a in derived["top_problems"]]
        refs += [i["evidence_id"] for i in derived.get("comparison_to_baseline", {}).get("items", []) if "evidence_id" in i]
        refs = list(dict.fromkeys(refs))
        evidence = [evidence_all[r] for r in refs if r in evidence_all]

        scenarios.append({
            "scenario_id": sid,
            "short_title": _short_title(scen, idx),
            "kpi": derived["kpi"],
            "analysis": {k: derived["analysis"][k] for k in ("status", "solver_warnings")},
            "alerts": [{"rule": a["rule"], "severity": a["severity"], "object": a["object"], "value": a["value"],
                        "unit": a["unit"], "time_h": a["time_h"], "evidence_id": a["evidence_id"]}
                       for a in derived["top_problems"]],
            "evidence": evidence,
            "baseline_delta": derived.get("comparison_to_baseline", {}),
            "context_json": ctx_json,
            "cases": cases,
            "probe_questions": [{"id": "observations", "text": "Главные наблюдаемые отклонения (с числами и E-ссылками)?"},
                                {"id": "causes", "text": "Наиболее вероятная причина и 1–2 альтернативы; чем их различить?"},
                                {"id": "limitations", "text": "Что по этим данным утверждать нельзя?"}],
            "truth": {
                "summary": "; ".join(e["note"] for e in scen["edits"]) or "правок не вносилось (базовый режим)",
                "primary_fault": scen["truth"].get("primary_fault"),
                "fault_severity": scen["truth"].get("fault_severity"),
                "expected_effects": scen["truth"].get("expected_effects", []),
            },
        })

    data = {
        "batch_id": batch["batch_id"], "expert_id": batch["expert_id"], "created": common.now_iso(),
        "categories": categories, "severities": severities, "confidence": confidence,
        "check_actions": check_actions, "scenarios": scenarios,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")   # безопасная вставка в <script>
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload)
    out_dir = common.ensure_dir(common.ROOT / PATHS["out"])
    out = out_dir / f"ExpertCasePack_{batch['batch_id']}.html"
    out.write_text(html, encoding="utf-8")
    return out


# пути по умолчанию (переопределяются флагами — удобно для проверок во временном каталоге)
PATHS = {"scenarios": "data/scenarios", "pending": "data/cases/pending",
         "batches": "data/batches", "out": "tools"}


def main() -> None:
    ap = argparse.ArgumentParser(description="HTML-форма для эксперта")
    ap.add_argument("--batch", default=None, help="путь к batch_*.json")
    ap.add_argument("--all", action="store_true", help="собрать формы для всех партий")
    ap.add_argument("--batches-dir", default="data/batches")
    ap.add_argument("--cases-dir", default="data/cases/pending")
    ap.add_argument("--scenarios-dir", default="data/scenarios")
    ap.add_argument("--out-dir", default="tools")
    args = ap.parse_args()

    PATHS.update(scenarios=args.scenarios_dir, pending=args.cases_dir,
                 batches=args.batches_dir, out=args.out_dir)

    if args.all or not args.batch:
        for fp in sorted((common.ROOT / args.batches_dir).glob("batch_*.json")):
            out = build_pack(fp)
            print(f"{fp.name} → {out.name} ({common.human_size(out.stat().st_size)})")
    else:
        out = build_pack(Path(args.batch))
        print(f"→ {out}")


if __name__ == "__main__":
    main()
