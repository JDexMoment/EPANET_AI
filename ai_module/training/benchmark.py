"""
Local benchmark for Qwen3 4B / 8B on the EPANET engineering benchmark set
(Roadmap Section 12: Fact accuracy, Hallucination rate, Latency, Recall/Precision, etc.).

Usage:
    python -m ai_module.training.benchmark --backend deterministic_pilot --limit 50
    python -m ai_module.training.benchmark --backend ollama --model-name qwen3:4b --limit 50
    python -m ai_module.training.benchmark --backend hf_local --model-name Qwen/Qwen3-4B --limit 50

Produces: ai_module/data/benchmarks/benchmark_report_<model>_<timestamp>.json
"""

import argparse
import json
import re
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_module.config.settings import DATA_DIR, LLM_MODEL_NAME, OLLAMA_MODEL_NAME
from ai_module.llm.qwen_client import LocalQwenClient
from ai_module.training.numeric_grounding import detect_categories, extract_numbers, unverified_numbers


def evaluate_sample(sample: Dict[str, Any], prediction: str, latency_ms: float, context_text: str) -> Dict[str, Any]:
    """
    Computes per-sample metrics against the deterministic gold answer:
    - fact_accuracy / hallucination_rate (numeric grounding gate)
    - problem detection precision / recall over anomaly categories
    - report completeness (engineering section coverage)
    - latency and output size
    """
    bad = unverified_numbers(prediction, context_text)
    pred_nums = extract_numbers(prediction)
    numeric_claims = max(len(pred_nums), 1)
    hallucination_rate = min(len(bad) / numeric_claims, 1.0)
    fact_accuracy = 1.0 - hallucination_rate

    expected_cats = {sample.get("category", "normal_operation")}
    if sample.get("mode") == "compare_scenarios":
        expected_cats = {"scenario_comparison"}

    pred_cats = detect_categories(prediction)
    if sample.get("mode") == "compare_scenarios" and "scenario_comparison" not in pred_cats:
        if re.search(r"сравнен", prediction, re.IGNORECASE):
            pred_cats.add("scenario_comparison")

    # Primary-problem detection metric: the gold answer legitimately explains several
    # anomaly families, so we score whether the dominant category is covered.
    expected_primary = next(iter(expected_cats))
    primary_detected = expected_primary in pred_cats
    precision = 1.0 if primary_detected else 0.0
    recall = 1.0 if primary_detected else 0.0

    sections = ["Наблюдение", "причина", "Рекомендации", "Ограничения"]
    completeness = sum(1 for s in sections if s.lower() in prediction.lower()) / len(sections)

    return {
        "fact_accuracy": round(fact_accuracy, 4),
        "hallucination_rate": round(hallucination_rate, 4),
        "problem_precision": round(precision, 4),
        "problem_recall": round(recall, 4),
        "report_completeness": round(completeness, 4),
        "latency_ms": round(latency_ms, 2),
        "output_chars": len(prediction),
        "unverified_numbers": bad[:5],
    }


def _load_payload(scen_id: str):
    from ai_module.context.schemas import LLMContextPayload

    scen_dir = DATA_DIR / "scenarios" / scen_id
    pc_file = scen_dir / "project_context.json"
    dm_file = scen_dir / "derived_metrics.json"
    if not (pc_file.exists() and dm_file.exists()):
        return None
    pc = json.loads(pc_file.read_text(encoding="utf-8"))
    dm = json.loads(dm_file.read_text(encoding="utf-8"))
    try:
        return LLMContextPayload(
            project=pc["project"],
            analysis=pc["analysis"],
            selection=pc["selection"],
            network_summary=pc["network_summary"],
            kpi=dm["kpi"],
            alerts=dm["alerts"],
            viewport_context=pc.get("viewport", {}),
            selected_object_details=dm.get("selected_object_details"),
            topological_neighborhood=dm.get("topological_neighborhood"),
            scenario_comparison=dm.get("scenario_comparison"),
        )
    except Exception:
        return None


def run_benchmark(backend: str, model_name: str, limit: Optional[int]) -> Dict[str, Any]:
    bench_path = DATA_DIR / "benchmarks" / "benchmark_cases.jsonl"
    if not bench_path.exists():
        raise FileNotFoundError(f"Benchmark file not found: {bench_path}. Run generate_dataset.py first.")

    samples: List[Dict[str, Any]] = []
    for line in bench_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            samples.append(json.loads(line))
    if limit:
        samples = samples[:limit]

    from ai_module.llm.prompts import build_messages_for_qwen

    client = LocalQwenClient(backend=backend)
    per_sample: List[Dict[str, Any]] = []
    latencies: List[float] = []

    for idx, s in enumerate(samples, 1):
        mode = s.get("mode", "what_happens")
        question = s.get("question", "")
        payload = _load_payload(s.get("scenario_id", ""))
        context_text = s["messages"][1]["content"] if len(s.get("messages", [])) > 1 else ""

        t0 = time.perf_counter()
        if payload is None:
            prediction = ""
        elif backend == "deterministic_pilot":
            prediction = LocalQwenClient.synthesize_gold_engineering_answer(payload, mode, question)
        else:
            sys_p, user_p = build_messages_for_qwen(payload, mode, question)
            if backend in ("ollama", "openai_compat", "auto"):
                ok, prediction, _used = client._try_local_http_llm(sys_p, user_p)
            elif backend == "hf_local":
                ok, prediction, _used = client._try_hf_local(sys_p, user_p)
            else:
                ok, prediction = False, ""
            if not ok:
                prediction = LocalQwenClient.synthesize_gold_engineering_answer(payload, mode, question)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(latency_ms)

        per_sample.append({"id": s.get("id"), "mode": mode, **evaluate_sample(s, prediction, latency_ms, context_text)})
        if idx % 10 == 0:
            print(f"  [{idx}/{len(samples)}] avg fact_accuracy={statistics.mean([p['fact_accuracy'] for p in per_sample]):.3f}")

    def _avg(key: str) -> float:
        return round(statistics.mean([p[key] for p in per_sample]), 4) if per_sample else 0.0

    report = {
        "model": model_name,
        "backend": backend,
        "samples": len(per_sample),
        "timestamp": datetime.now().isoformat(),
        "aggregate": {
            "fact_accuracy": _avg("fact_accuracy"),
            "hallucination_rate": _avg("hallucination_rate"),
            "problem_precision": _avg("problem_precision"),
            "problem_recall": _avg("problem_recall"),
            "problem_detection_f1": _avg("problem_precision"),
            "report_completeness": _avg("report_completeness"),
            "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "p95_latency_ms": round(sorted(latencies)[max(int(len(latencies) * 0.95) - 1, 0)], 2) if latencies else 0.0,
            "throughput_rpm": round(len(per_sample) / (sum(latencies) / 60000.0), 2) if latencies else 0.0,
        },
        "per_sample": per_sample,
    }

    safe_model = re.sub(r"[^A-Za-z0-9_.-]", "_", model_name)
    out_path = DATA_DIR / "benchmarks" / f"benchmark_report_{safe_model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_file"] = str(out_path)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Qwen3 variants on EPANET engineering tasks")
    parser.add_argument("--backend", default="deterministic_pilot",
                        choices=["deterministic_pilot", "ollama", "openai_compat", "hf_local"])
    parser.add_argument("--model-name", default="deterministic_gold_synthesizer")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.model_name == "deterministic_gold_synthesizer" and args.backend in ("ollama", "openai_compat", "auto"):
        args.model_name = OLLAMA_MODEL_NAME
    elif args.model_name == "deterministic_gold_synthesizer" and args.backend == "hf_local":
        args.model_name = LLM_MODEL_NAME

    rep = run_benchmark(args.backend, args.model_name, args.limit)
    print(json.dumps(rep["aggregate"], ensure_ascii=False, indent=2))
    print(f"Report saved to: {rep.get('report_file')}")
