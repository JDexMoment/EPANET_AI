import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List

from ai_module.config.settings import DATA_DIR
from ai_module.context.context_builder import ContextBuilder
from ai_module.llm.prompts import build_messages_for_qwen
from ai_module.llm.qwen_client import LocalQwenClient
from ai_module.reports.report_generator import ReportGenerator

MODES_AND_QUESTIONS = [
    ("what_happens", "Что сейчас происходит на экране и какие есть существенные отклонения в расчёте?"),
    ("find_problems", "Найди все инженерные проблемы и аномалии давлений, скоростей и уклонов в текущей модели."),
    ("explain_object", "Объясни параметры выбранного объекта, его суточный режим и влияние на прилегающие участки сети."),
    ("why_happened", "Почему возникла главная гидравлическая проблема на этом участке? Объясни на основе связей и потерь напора."),
    ("generate_report", "Составь полный инженерный отчёт по текущему гидравлическому расчёту с разделением фактов и рекомендаций."),
    ("ask_question", "Достаточен ли свободный напор в сети и есть ли участки с риском недостачи воды в часы пикового водоразбора?"),
    ("ask_question", "Какая труба создаёт наибольшие потери напора и как это связано с давлением в проблемном узле?"),
]


def build_dataset_from_raw_networks(max_periods_per_net: int = 4) -> Dict[str, Any]:
    """
    Scans `ai_module/data/raw_networks/*.inp`, runs EPANET 2.2 C-engine across multiple time steps
    and object selections, and writes:
      1. `ai_module/data/scenarios/scenario_XXXX/` with:
         - project_context.json
         - analysis_results.json
         - derived_metrics.json
         - qa_annotations.json (question, gold_answer, severity, category, evidence, report)
      2. `ai_module/data/sft_datasets/train_qwen3_chatml.jsonl` & `val_qwen3_chatml.jsonl`
      3. `ai_module/data/benchmarks/benchmark_cases.jsonl`
    """
    raw_dir = DATA_DIR / "raw_networks"
    scenarios_dir = DATA_DIR / "scenarios"
    sft_dir = DATA_DIR / "sft_datasets"
    bench_dir = DATA_DIR / "benchmarks"

    inp_files = sorted(raw_dir.glob("*.inp"))
    if not inp_files:
        raise FileNotFoundError(f"Нет файлов .inp в папке {raw_dir}")

    cb = ContextBuilder()
    qwen_synth = LocalQwenClient(backend="deterministic_pilot")

    sft_samples: List[Dict[str, Any]] = []
    scenario_counter = 0

    for inp_path in inp_files:
        # First probe simulation to see available periods and objects
        base_sim = cb.engine.run_simulation(str(inp_path), target_period=0)
        total_periods = base_sim["analysis"]["total_periods"]
        step_indices = sorted(list({0, min(3, total_periods - 1), min(12, total_periods - 1), total_periods - 1}))[:max_periods_per_net]

        nodes_list = [n["id"] for n in base_sim["topology"]["nodes"]]
        links_list = [l["id"] for l in base_sim["topology"]["links"]]

        for p_idx in step_indices:
            scenario_counter += 1
            scen_id = f"scenario_{scenario_counter:04d}"
            scen_folder = scenarios_dir / scen_id
            scen_folder.mkdir(parents=True, exist_ok=True)

            # Pick a focus object (e.g., node or pipe)
            focus_obj = nodes_list[p_idx % len(nodes_list)] if p_idx % 2 == 0 else links_list[p_idx % len(links_list)]

            payload, sim_data, analytics_res = cb.build_context(
                inp_file=str(inp_path),
                mode="what_happens",
                selected_id=focus_obj,
                target_period=p_idx,
            )

            project_context, analysis_results, derived_metrics = cb.split_for_dataset_storage(
                payload, sim_data, analytics_res
            )

            # Save the 3 core JSON files per Roadmap Section 9
            (scen_folder / "project_context.json").write_text(
                json.dumps(project_context, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (scen_folder / "analysis_results.json").write_text(
                json.dumps(analysis_results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (scen_folder / "derived_metrics.json").write_text(
                json.dumps(derived_metrics, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Determine top severity & category + evidence list
            if payload.alerts:
                top_severity = payload.alerts[0].severity
                top_category = payload.alerts[0].type
                evidence = [
                    {
                        "object": a.object,
                        "object_type": a.object_type,
                        "metric": a.metric_name,
                        "value": a.value,
                        "unit": a.unit,
                        "threshold": a.threshold,
                    }
                    for a in payload.alerts[:5]
                ]
            else:
                top_severity = "normal"
                top_category = "normal_operation"
                evidence = [
                    {
                        "object": payload.kpi.min_pressure_node,
                        "object_type": "junction",
                        "metric": "min_pressure_m",
                        "value": payload.kpi.min_pressure_m,
                        "unit": "m",
                    },
                    {
                        "object": payload.kpi.max_velocity_pipe,
                        "object_type": "pipe",
                        "metric": "max_velocity_mps",
                        "value": payload.kpi.max_velocity_mps,
                        "unit": "m/s",
                    },
                ]

            qa_records: List[Dict[str, Any]] = []
            gold_report_text = qwen_synth.synthesize_gold_engineering_answer(payload, "generate_report", "")

            for mode, q_text in MODES_AND_QUESTIONS:
                gold_answer = qwen_synth.synthesize_gold_engineering_answer(payload, mode, q_text)
                sys_prompt, user_prompt = build_messages_for_qwen(payload, mode, q_text)

                qa_item = {
                    "sample_id": f"{scen_id}_{mode}",
                    "scenario_id": scen_id,
                    "mode": mode,
                    "question": q_text,
                    "gold_answer": gold_answer,
                    "severity": top_severity,
                    "category": top_category,
                    "evidence": evidence,
                    "report": gold_report_text if mode == "generate_report" else "",
                }
                qa_records.append(qa_item)

                sft_samples.append({
                    "id": f"{scen_id}_{mode}",
                    "scenario_id": scen_id,
                    "mode": mode,
                    "severity": top_severity,
                    "category": top_category,
                    "evidence": evidence,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": gold_answer},
                    ],
                })

            (scen_folder / "qa_annotations.json").write_text(
                json.dumps(qa_records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (scen_folder / "gold_report.md").write_text(gold_report_text, encoding="utf-8")

    # Add scenario comparison sample if at least 2 district files exist
    base_dist = raw_dir / "city_district_si.inp"
    upgr_dist = raw_dir / "city_district_upgraded.inp"
    if base_dist.exists() and upgr_dist.exists():
        scenario_counter += 1
        scen_id = f"scenario_{scenario_counter:04d}"
        scen_folder = scenarios_dir / scen_id
        scen_folder.mkdir(parents=True, exist_ok=True)

        payload, sim_data, analytics_res = cb.build_context(
            inp_file=str(base_dist),
            mode="compare_scenarios",
            compare_inp_file=str(upgr_dist),
            target_period=12,
        )
        project_context, analysis_results, derived_metrics = cb.split_for_dataset_storage(
            payload, sim_data, analytics_res
        )
        (scen_folder / "project_context.json").write_text(
            json.dumps(project_context, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (scen_folder / "analysis_results.json").write_text(
            json.dumps(analysis_results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (scen_folder / "derived_metrics.json").write_text(
            json.dumps(derived_metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        q_text = "Сравни два сценария расчёта (до и после реконструкции трубы P-104) и объясни, что изменилось и где."
        gold_answer = qwen_synth.synthesize_gold_engineering_answer(payload, "compare_scenarios", q_text)
        sys_prompt, user_prompt = build_messages_for_qwen(payload, "compare_scenarios", q_text)
        evidence = [
            {
                "object": "J-104",
                "metric": "min_pressure_delta_m",
                "value": payload.scenario_comparison["kpi_deltas"]["min_pressure_delta_m"],
                "unit": "m",
            }
        ]
        (scen_folder / "qa_annotations.json").write_text(
            json.dumps([{
                "sample_id": f"{scen_id}_compare_scenarios",
                "scenario_id": scen_id,
                "mode": "compare_scenarios",
                "question": q_text,
                "gold_answer": gold_answer,
                "severity": "info",
                "category": "scenario_comparison",
                "evidence": evidence,
                "report": gold_answer,
            }], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (scen_folder / "gold_report.md").write_text(gold_answer, encoding="utf-8")
        sft_samples.append({
            "id": f"{scen_id}_compare_scenarios",
            "scenario_id": scen_id,
            "mode": "compare_scenarios",
            "severity": "info",
            "category": "scenario_comparison",
            "evidence": evidence,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": gold_answer},
            ],
        })

    # Shuffle deterministically and split 85% train / 15% val
    rng = random.Random(42)
    shuffled = list(sft_samples)
    rng.shuffle(shuffled)
    split_idx = max(1, int(len(shuffled) * 0.85))
    train_set = shuffled[:split_idx]
    val_set = shuffled[split_idx:]

    train_path = sft_dir / "train_qwen3_chatml.jsonl"
    val_path = sft_dir / "val_qwen3_chatml.jsonl"
    bench_path = bench_dir / "benchmark_cases.jsonl"

    with train_path.open("w", encoding="utf-8") as f:
        for item in train_set:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with val_path.open("w", encoding="utf-8") as f:
        for item in val_set:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with bench_path.open("w", encoding="utf-8") as f:
        for item in sft_samples:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return {
        "scenarios_generated": scenario_counter,
        "total_sft_samples": len(sft_samples),
        "train_samples": len(train_set),
        "val_samples": len(val_set),
        "train_file": str(train_path),
        "val_file": str(val_path),
        "benchmark_file": str(bench_path),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate EPANET AI scenarios and SFT JSONL dataset for Qwen3")
    parser.add_argument("--max-periods", type=int, default=4, help="Time steps to sample per INP network")
    args = parser.parse_args()
    stats = build_dataset_from_raw_networks(max_periods_per_net=args.max_periods)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
