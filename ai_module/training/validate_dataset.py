"""
Dataset validation & quality gate for the EPANET AI SFT dataset.

Checks (per Roadmap Section 9 & 12):
  1. Scenario folder completeness: project_context.json, analysis_results.json,
     derived_metrics.json, qa_annotations.json, gold_report.md.
  2. ChatML message structure (system / user / assistant).
  3. Zero-hallucination gate: every numeric claim in the gold answer must be
     grounded in the JSON context (see training/numeric_grounding.py).
  4. Dataset-level coverage gate: all 7 AI modes must be present in the corpus.

Exit code 0 = PASSED, 1 = FAILED.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from ai_module.config.settings import DATA_DIR
from ai_module.training.numeric_grounding import unverified_numbers

REQUIRED_SCENARIO_FILES = (
    "project_context.json",
    "analysis_results.json",
    "derived_metrics.json",
    "qa_annotations.json",
    "gold_report.md",
)

REQUIRED_MODES = {
    "what_happens",
    "explain_object",
    "find_problems",
    "why_happened",
    "generate_report",
    "compare_scenarios",
    "ask_question",
}


def validate_scenario_folder(sd: Path) -> List[str]:
    problems: List[str] = []
    for req in REQUIRED_SCENARIO_FILES:
        if not (sd / req).exists():
            problems.append(f"{sd.name}: missing {req}")

    qa_file = sd / "qa_annotations.json"
    if qa_file.exists():
        try:
            qa = json.loads(qa_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            problems.append(f"{sd.name}: qa_annotations.json is not valid JSON")
            return problems
        if not any(isinstance(q, dict) and q.get("gold_answer") for q in qa):
            problems.append(f"{sd.name}: qa_annotations.json contains no gold_answer records")

        for core_file in ("project_context.json", "analysis_results.json", "derived_metrics.json"):
            fp = sd / core_file
            if fp.exists():
                try:
                    json.loads(fp.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    problems.append(f"{sd.name}: {core_file} is not valid JSON")
    return problems


def collect_mode_coverage(scenarios_dir: Path) -> Set[str]:
    covered: Set[str] = set()
    for sd in scenarios_dir.iterdir():
        if not sd.is_dir():
            continue
        qa_file = sd / "qa_annotations.json"
        if not qa_file.exists():
            continue
        try:
            qa = json.loads(qa_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for q in qa:
            if isinstance(q, dict) and q.get("mode"):
                covered.add(q["mode"])
    return covered


def validate_jsonl(jpath: Path) -> Dict[str, Any]:
    total = 0
    fact_ok = 0
    unverified: List[Dict[str, Any]] = []
    bad_structure = 0

    for line_no, line in enumerate(jpath.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        total += 1
        obj = json.loads(line)
        msgs = obj.get("messages", [])
        if len(msgs) != 3 or [m.get("role") for m in msgs] != ["system", "user", "assistant"]:
            bad_structure += 1
            continue

        user_ctx = msgs[1]["content"]
        gold_ans = msgs[2]["content"]
        bad_nums = unverified_numbers(gold_ans, user_ctx)

        if bad_nums:
            unverified.append({"id": obj.get("id"), "line": line_no, "numbers": bad_nums[:8]})
        else:
            fact_ok += 1

    return {
        "samples": total,
        "bad_structure": bad_structure,
        "fact_consistent": fact_ok,
        "unverified": unverified,
        "fact_accuracy": round(fact_ok / max(total, 1), 4),
    }


def validate_all() -> Dict[str, Any]:
    scenarios_dir = DATA_DIR / "scenarios"
    sft_dir = DATA_DIR / "sft_datasets"

    scenario_dirs = sorted([d for d in scenarios_dir.iterdir() if d.is_dir()])
    folder_problems: List[str] = []
    for sd in scenario_dirs:
        folder_problems.extend(validate_scenario_folder(sd))

    covered_modes = collect_mode_coverage(scenarios_dir)
    missing_modes = REQUIRED_MODES - covered_modes

    train_res = validate_jsonl(sft_dir / "train_qwen3_chatml.jsonl") if (sft_dir / "train_qwen3_chatml.jsonl").exists() else {}
    val_res = validate_jsonl(sft_dir / "val_qwen3_chatml.jsonl") if (sft_dir / "val_qwen3_chatml.jsonl").exists() else {}

    total_samples = train_res.get("samples", 0) + val_res.get("samples", 0)
    fact_ok = train_res.get("fact_consistent", 0) + val_res.get("fact_consistent", 0)

    problems = list(folder_problems)
    for m in sorted(missing_modes):
        problems.append(f"dataset: AI mode '{m}' is not covered by any scenario")
    problems += [f"train: unverified numbers in {u['id']} -> {u['numbers']}" for u in train_res.get("unverified", [])]
    problems += [f"val: unverified numbers in {u['id']} -> {u['numbers']}" for u in val_res.get("unverified", [])]
    if train_res.get("bad_structure"):
        problems.append(f"train: {train_res['bad_structure']} samples with invalid ChatML structure")
    if val_res.get("bad_structure"):
        problems.append(f"val: {val_res['bad_structure']} samples with invalid ChatML structure")

    return {
        "scenario_folders": len(scenario_dirs),
        "mode_coverage": sorted(covered_modes),
        "missing_modes": sorted(missing_modes),
        "total_sft_samples": total_samples,
        "fact_consistent_samples": fact_ok,
        "fact_accuracy_rate": round(fact_ok / max(total_samples, 1), 4),
        "train_detail": {k: v for k, v in train_res.items() if k != "unverified"},
        "val_detail": {k: v for k, v in val_res.items() if k != "unverified"},
        "problems": problems,
        "status": "PASSED" if not problems else "FAILED",
    }


if __name__ == "__main__":
    report = validate_all()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["status"] == "PASSED" else 1)
