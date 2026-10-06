"""Строит «кейсы» (единицы датасета) из сгенерированных сценариев.

Кейс = вопрос + замороженные факты (evidence) + пустые поля gold для инженера.
Инженер НЕ пишет ответ с нуля: он видит контекст, который увидит модель,
и заполняет эталон.

Запуск:
    python -m src.dataset.build_cases
    python -m src.dataset.build_cases --manifest data/scenarios/manifest.jsonl
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .. import analytics, common, context_builder

# сколько кейсов каких типов создаём на сценарий
REPORT_EVERY = 4          # каждый 4-й сценарий — с полным «золотым» отчётом (~2 на партию из 8)
PROBE_QUESTIONS = [
    ("observations", "Перечислите главные наблюдаемые отклонения (с числами и ссылками E-xxx)."),
    ("causes", "Назовите наиболее вероятную причину и 1-2 альтернативы; чем их различить на сети."),
    ("limitations", "Что по этим данным утверждать НЕЛЬЗЯ (ограничения вывода)?"),
]

QUESTION_TEMPLATES = {
    "whats_happening": "Что происходит в сети? Кратко опишите режим (сутки) и главные отклонения.",
    "find_problems": "Какие проблемы вы видите в этом расчёте? Что требует внимания в первую очередь?",
    "why_happened": "Почему возникли эти отклонения? Дайте наиболее вероятные причины и способ их проверки.",
    "explain_object": "Объясните параметры объекта {obj} и его влияние на систему.",
    "make_report": "Составьте инженерный отчёт по этому расчёту.",
    "compare_scenarios": "Сравните текущий расчёт с базовым: что изменилось, где и насколько.",
}


def _evidence_for(derived: dict, evidence_all: dict, refs: list[str], limit: int = 30) -> list[dict]:
    out = []
    for r in refs[:limit]:
        if r in evidence_all:
            out.append(evidence_all[r])
    return out


def make_case(scenario_dir: Path, derived: dict, mode: str, question: str,
              selection: dict, ctx: dict, case_idx: int) -> dict:
    """Собирает один кейс: факты + пустой gold."""
    sid = derived["scenario_id"]
    net = derived["network_id"]
    evidence_all = common.read_json(scenario_dir / "derived" / "evidence.json")

    # какие evidence попадают в этот кейс: алерты + фокус
    refs: list[str] = list(derived.get("kpi_evidence_refs", []))
    refs += [a["evidence_id"] for a in derived["top_problems"]]
    focus = ctx.get("focus", {})
    if focus:
        refs += [a["evidence_id"] for a in focus.get("local_alerts", [])]
    for it in derived.get("comparison_to_baseline", {}).get("items", []):
        if "evidence_id" in it:
            refs.append(it["evidence_id"])
    refs = list(dict.fromkeys(refs))

    focus_obj = focus.get("object", {}).get("id") if focus else None
    question = question.format(obj=focus_obj) if "{obj}" in question else question

    return {
        "schema_version": "1.0",
        "case_id": f"c_{sid}__{mode}__{case_idx:02d}",
        "scenario_id": sid, "network_id": net, "created": common.now_iso(),
        "mode": mode, "question": question,
        "selection": selection,
        "facts": {
            "context_digest": common.sha256_text(
                (scenario_dir / "derived" / f"llm_context_{mode}.json").read_text(encoding="utf-8")
                if (scenario_dir / "derived" / f"llm_context_{mode}.json").exists() else ""),
            "llm_context_ref": _rel(scenario_dir / "derived" / f"llm_context_{mode}.json"),
            "evidence": _evidence_for(derived, evidence_all, refs),
        },
        "label": {"has_problem": None, "category": None, "secondary_categories": [], "severity": None,
                  "primary_objects": [], "evidence_refs": [], "confidence": None, "likely_cause": None},
        "gold": {"answer": None,
                 "answer_structured": {"observations": [], "probable_causes": [], "checks": [],
                                       "recommendations": [], "limitations": [], "evidence_refs": []},
                 "report_markdown": None,
                 "checklist": {"must_not_claim": [], "needs_verification": []}},
        "probe_questions": [{"id": k, "text": t, "answer": None} for k, t in PROBE_QUESTIONS],
        "annotation": {"annotator_id": None, "annotator_role": None, "annotated_at": None,
                       "time_spent_min": None, "double_annotated": False, "reviewer_id": None,
                       "review_status": "draft", "review_comments": None},
        "eval": {"required_facts": [], "forbidden_claims": [], "required_sections": []},
    }


def _rel(path) -> str:
    """Путь относительно корня проекта, если он внутри него (иначе — как есть)."""
    try:
        return str(Path(path).resolve().relative_to(common.ROOT.resolve()))
    except ValueError:
        return str(path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Построение кейсов датасета")
    ap.add_argument("--manifest", default="data/scenarios/manifest.jsonl")
    ap.add_argument("--scenarios-dir", default="data/scenarios")
    ap.add_argument("--out", default="data/cases/pending")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    manifest = common.read_jsonl(args.manifest)
    out_dir = common.ensure_dir(common.ROOT / args.out)
    n_new = 0
    for i, rec in enumerate(manifest):
        if rec.get("status") != "ok":
            continue
        sid = rec["scenario_id"]
        if args.only and sid != args.only:
            continue
        sdir = common.ROOT / args.scenarios_dir / sid
        derived = common.read_json(sdir / "derived" / "derived_metrics.json")

        # контексты, которые увидит модель, замораживаем сразу
        ctxs = {}
        for mode in ("whats_happening", "make_report", "find_problems"):
            ctxs[mode] = context_builder.build_context(sdir, mode=mode)
            common.write_json(sdir / "derived" / f"llm_context_{mode}.json", ctxs[mode])

        # объект в фокусе = худший объект из Top-проблем
        worst_obj = derived["top_problems"][0]["object"] if derived["top_problems"] else None
        is_faulted = bool(rec.get("status") == "ok" and common.read_json(sdir / "scenario.json")["truth"]["is_faulted"])
        report_day = (i % REPORT_EVERY == 0)

        plans = [("whats_happening", QUESTION_TEMPLATES["whats_happening"], {"type": "whole_network", "id": None}, "whats_happening"),
                 ("find_problems", QUESTION_TEMPLATES["find_problems"], {"type": "whole_network", "id": None}, "find_problems")]
        if is_faulted:
            plans.append(("why_happened", QUESTION_TEMPLATES["why_happened"],
                          {"type": "whole_network", "id": None}, "whats_happening"))
            plans.append(("compare_scenarios", QUESTION_TEMPLATES["compare_scenarios"],
                          {"type": "whole_network", "id": None}, "find_problems"))
        if worst_obj:
            plans.append(("explain_object", QUESTION_TEMPLATES["explain_object"],
                          {"type": "junction" if worst_obj.startswith("J") else "pipe", "id": worst_obj}, "whats_happening"))
        if report_day:
            plans.append(("make_report", QUESTION_TEMPLATES["make_report"], {"type": "whole_network", "id": None}, "make_report"))

        for idx, (mode, q, sel, ctx_mode) in enumerate(plans):
            ctx = ctxs.get(ctx_mode) or context_builder.build_context(sdir, mode=ctx_mode, selection=sel)
            if sel.get("id"):
                ctx = context_builder.build_context(sdir, mode=ctx_mode, selection=sel)
                common.write_json(sdir / "derived" / f"llm_context_{mode}.json", ctx)
            case = make_case(sdir, derived, mode, q, sel, ctx, idx)
            fp = out_dir / f"{case['case_id']}.json"
            if not fp.exists():
                common.write_json(fp, case)
                n_new += 1
    print(f"Создано новых кейсов: {n_new} → {out_dir}")
    print("Дальше: make_batches.py → make_expert_pack.py → инженеры заполняют gold → import_expert_json.py")


if __name__ == "__main__":
    main()
