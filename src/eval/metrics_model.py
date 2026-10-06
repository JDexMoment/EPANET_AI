"""Метрики ПОСЛЕ обучения: бенчмарк модели (roadmap п.12).

Принимает predictions.jsonl — журнал ответов модели на тестовый набор:

    {"case_id": "...", "answer": "...", "latency_s": 2.4, "vram_mb": 7800, "run": "qwen3.5-9b-lora-v1"}

Считает:
  * Fact accuracy      — доля чисел в ответе, подтверждённых контекстом/evidence;
  * Hallucination rate — 1 − fact accuracy;
  * Citation rate      — доля числовых утверждений со ссылкой E-xxx;
  * Required facts recall / forbidden claims — по разметке кейса;
  * Report completeness — наличие обязательных разделов (для make_report);
  * Latency / VRAM / throughput.

Запуск (пример):
    python -m src.eval.metrics_model --pred data/eval/predictions.example.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .. import common

sys_num_re = None
NUM_WITH_UNIT = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*(м вод\.ст\.|м/с|л/с|м³|м3|м\b|%)", re.IGNORECASE)
EVID_RE = re.compile(r"\bE-\d{3,}\b")
REPORT_SECTIONS = ["наблюд", "проблем", "причин", "рекоменд", "огранич"]


def _allowed_numbers(ctx_text: str, reference: str) -> set[str]:
    nums = set()
    for m in NUM_WITH_UNIT.finditer(ctx_text or ""):
        nums.add(f"{float(m.group(1).replace(',', '.')):g}")
    for m in re.finditer(r"(-?\d+(?:[.,]\d+)?)", reference or ""):
        nums.add(f"{float(m.group(1).replace(',', '.')):g}")
    return nums


def _grounded(value: str, allowed: set[str]) -> bool:
    v = float(value)
    for a in allowed:
        try:
            fa = float(a)
        except ValueError:
            continue
        if abs(v - fa) <= max(0.5, 0.1 * abs(fa)):
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Бенчмарк модели")
    ap.add_argument("--pred", default="data/eval/predictions.jsonl")
    ap.add_argument("--eval-set", default="data/splits/eval_test.jsonl")
    ap.add_argument("--out", default="data/eval/model_scores.json")
    args = ap.parse_args()

    preds = common.read_jsonl(args.pred)
    eval_rows = {r["case_id"]: r for r in common.read_jsonl(args.eval_set)} if (common.ROOT / args.eval_set).exists() else {}

    per_run: dict[str, list[dict]] = {}
    for p in preds:
        case = eval_rows.get(p["case_id"], {})
        ctx = case.get("context", "")
        ref = case.get("reference_answer", "")
        allowed = _allowed_numbers(ctx, ref)
        answer = p.get("answer", "")

        claims = list(NUM_WITH_UNIT.finditer(answer))
        grounded = sum(1 for m in claims if _grounded(m.group(1).replace(",", "."), allowed))
        fact_acc = grounded / len(claims) if claims else None

        sentences = re.split(r"(?<=[.!?])\s+", answer)
        num_sentences = [s for s in sentences if NUM_WITH_UNIT.search(s)]
        cited = sum(1 for s in num_sentences if EVID_RE.search(s))
        citation_rate = cited / len(num_sentences) if num_sentences else None

        req = case.get("required_facts", [])
        req_hit = 0
        for f in req:
            must = f.get("must_contain") or []
            if all(str(x) in answer for x in must):
                req_hit += 1
        req_recall = req_hit / len(req) if req else None

        forbidden = [w for w in case.get("forbidden_claims", []) if w.lower() in answer.lower()]
        sections = sum(1 for s in REPORT_SECTIONS if s in answer.lower())
        completeness = sections / len(REPORT_SECTIONS) if case.get("mode") == "make_report" else None

        per_run.setdefault(p.get("run", "default"), []).append({
            "case_id": p["case_id"], "fact_accuracy": fact_acc, "citation_rate": citation_rate,
            "required_recall": req_recall, "forbidden_hits": len(forbidden),
            "report_completeness": completeness, "latency_s": p.get("latency_s"),
            "vram_mb": p.get("vram_mb"), "n_claims": len(claims),
        })

    summary = {}
    for run, rows in per_run.items():
        def avg(key):
            vals = [r[key] for r in rows if r[key] is not None]
            return round(sum(vals) / len(vals), 3) if vals else None
        lats = sorted(r["latency_s"] for r in rows if r.get("latency_s"))
        summary[run] = {
            "cases": len(rows),
            "fact_accuracy": avg("fact_accuracy"),
            "hallucination_rate": (round(1 - avg("fact_accuracy"), 3) if avg("fact_accuracy") is not None else None),
            "citation_rate": avg("citation_rate"),
            "required_facts_recall": avg("required_recall"),
            "forbidden_claims_total": sum(r["forbidden_hits"] for r in rows),
            "report_completeness": avg("report_completeness"),
            "latency_mean_s": round(sum(lats) / len(lats), 2) if lats else None,
            "latency_p95_s": lats[int(0.95 * (len(lats) - 1))] if lats else None,
            "throughput_rps": round(1 / (sum(lats) / len(lats)), 2) if lats else None,
            "vram_mb_max": max([r["vram_mb"] for r in rows if r.get("vram_mb")] or [None]) if any(r.get("vram_mb") for r in rows) else None,
        }

    common.write_json(args.out, summary)
    print("=" * 78)
    print("БЕНЧМАРК МОДЕЛИ")
    print("=" * 78)
    for run, s in summary.items():
        print(f"\n[{run}]  кейсов: {s['cases']}")
        for k, v in s.items():
            if k != "cases":
                print(f"   {k:26s} {v}")
    print(f"\n→ {args.out}")
    print("\nПороговые значения для допуска к production (roadmap п.12):")
    print("   fact_accuracy ≥ 0.95 · hallucination_rate ≤ 0.05 · required_facts_recall ≥ 0.80")
    print("   forbidden_claims_total = 0 · report_completeness ≥ 0.8 · latency в рамках SLA")


if __name__ == "__main__":
    main()
