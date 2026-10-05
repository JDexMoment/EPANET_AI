"""Контроль качества разметки (IQA) и статистика датасета.

Считает:
  * согласие двух инженеров по метке (category / severity / has_problem) —
    на сценариях с двойной разметкой;
  * пересечение ссылок evidence (Jaccard) и схожесть текстов ответов;
  * статистику по датасету: сколько кейсов по режимам, категориям, длинам.

Запуск:
    python -m src.dataset.check_quality --dir data/cases/filled
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .. import common


def _tokens(text: str) -> set[str]:
    return {t.strip(".,;:()«»\"'").lower() for t in (text or "").split() if len(t) > 3}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def main() -> None:
    ap = argparse.ArgumentParser(description="Контроль качества разметки")
    ap.add_argument("--dir", default="data/cases/filled")
    ap.add_argument("--out", default="data/eval/quality_report.json")
    args = ap.parse_args()

    cdir = common.ROOT / args.dir
    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for fp in sorted(cdir.glob("c_*.json")):
        c = common.read_json(fp)
        by_scenario[c["scenario_id"]].append(c)

    # ── IQA по сценариям с двойной разметкой
    iqa = {"scenarios_double": 0, "label_agreement": {}, "answer_similarity": [], "pairs": []}
    for sid, cases in by_scenario.items():
        annotators = {c["annotation"].get("annotator_id") for c in cases
                      if c.get("annotation", {}).get("annotator_id")}
        # в filled-папке один кейс = последняя аннотация; двойная появляется,
        # когда в inbox пришли две партии (см. assignments.json + review)
        if len(annotators) < 2:
            continue
        iqa["scenarios_double"] += 1
        by_annot: dict[str, list[dict]] = defaultdict(list)
        for c in cases:
            by_annot[c["annotation"]["annotator_id"]].append(c)
        ids = sorted(by_annot)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = by_annot[ids[i]], by_annot[ids[j]]
                la, lb = a[0]["label"], b[0]["label"]
                pair = {"scenario_id": sid, "annotators": [ids[i], ids[j]],
                        "category_agree": la.get("category") == lb.get("category"),
                        "severity_agree": la.get("severity") == lb.get("severity"),
                        "has_problem_agree": la.get("has_problem") == lb.get("has_problem"),
                        "evidence_jaccard": round(jaccard(set(la.get("evidence_refs") or []),
                                                          set(lb.get("evidence_refs") or [])), 3)}
                # схожесть текстов ответов одинакового режима
                for ca in a:
                    for cb in b:
                        if ca["mode"] == cb["mode"] and (ca["gold"] or {}).get("answer") and (cb["gold"] or {}).get("answer"):
                            pair["answer_jaccard"] = round(jaccard(_tokens(ca["gold"]["answer"]),
                                                                   _tokens(cb["gold"]["answer"])), 3)
                iqa["pairs"].append(pair)

    if iqa["pairs"]:
        iqa["label_agreement"] = {
            "category": round(sum(p["category_agree"] for p in iqa["pairs"]) / len(iqa["pairs"]), 3),
            "severity": round(sum(p["severity_agree"] for p in iqa["pairs"]) / len(iqa["pairs"]), 3),
            "has_problem": round(sum(p["has_problem_agree"] for p in iqa["pairs"]) / len(iqa["pairs"]), 3),
            "evidence_jaccard_mean": round(sum(p["evidence_jaccard"] for p in iqa["pairs"]) / len(iqa["pairs"]), 3),
        }
        sims = [p["answer_jaccard"] for p in iqa["pairs"] if "answer_jaccard" in p]
        if sims:
            iqa["answer_similarity"] = {"mean": round(sum(sims) / len(sims), 3), "n": len(sims)}

    # ── статистика датасета
    all_cases = [c for cases in by_scenario.values() for c in cases]
    filled = [c for c in all_cases if (c["gold"] or {}).get("answer") or (c["gold"] or {}).get("report_markdown")]
    stats = {
        "cases_total": len(all_cases),
        "cases_filled": len(filled),
        "scenarios": len(by_scenario),
        "by_mode": dict(Counter(c["mode"] for c in all_cases)),
        "by_category": dict(Counter((c["label"] or {}).get("category") or "—" for c in filled)),
        "by_severity": dict(Counter((c["label"] or {}).get("severity") or "—" for c in filled)),
        "by_annotator": dict(Counter((c["annotation"] or {}).get("annotator_id") or "—" for c in filled)),
        "avg_answer_words": round(sum(len(((c['gold'] or {}).get('answer') or '').split()) for c in filled) / max(1, len(filled)), 1),
        "avg_time_min": round(sum((c["annotation"] or {}).get("time_spent_min") or 0 for c in filled) / max(1, len(filled)), 1),
    }

    report = {"dataset": stats, "iqa": iqa}
    common.write_json(args.out, report)

    print("=== Датасет ==="); 
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("\n=== IQA (двойная разметка) ===")
    if iqa["pairs"]:
        for k, v in iqa["label_agreement"].items():
            print(f"  {k}: {v}")
        print(f"  схожесть текстов: {iqa['answer_similarity']}")
    else:
        print("  нет пересечений двойной разметки (появится после двух партий по одним сценариям)")
    print(f"\nОтчёт → {args.out}")


if __name__ == "__main__":
    main()
