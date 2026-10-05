"""ТЕСТ КОНВЕЙЕРА (не данные для обучения!).

Имитирует выгрузку из HTML-формы: формирует JSON той же структуры, что присылает
инженер, но ответы собирает автоматически из evidence (дословно), чтобы проверить
весь путь: inbox → import → validate → quality → export.

Запуск:
    python tools/simulate_expert_export.py --batch data/batches/batch_exp_01_01.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import common  # noqa: E402

LIMITATIONS = ("Ограничение: разметка сформирована автоматически для проверки конвейера, "
               "числа взяты из evidence без инженерной интерпретации.")


REPORT_HEADER = ("# Отчёт (автотест конвейера)\n\n## Исходные условия\n{ctx}\n\n"
                 "## Результаты\n{res}\n\n## Проблемы\n{prob}\n\n## Вероятные причины\n{cause}\n\n"
                 "## Рекомендации\n{rec}\n\n## Ограничения\n{lim}\n")


def make_payload(sid: str, case_ids: list[str]) -> dict:
    sdir = common.ROOT / "data" / "scenarios" / sid
    derived = common.read_json(sdir / "derived" / "derived_metrics.json")
    ev = common.read_json(sdir / "derived" / "evidence.json")
    scen = common.read_json(sdir / "scenario.json")
    top = derived["top_problems"][:4] or []
    obs = [f"{ev[a['evidence_id']]['statement']} ({a['evidence_id']})"
           for a in top if a["evidence_id"] in ev]
    refs = [a["evidence_id"] for a in top]
    for it in derived.get("comparison_to_baseline", {}).get("items", [])[:3]:
        if it.get("evidence_id"):
            obs.append(f"{ev[it['evidence_id']]['statement']} ({it['evidence_id']})")
            refs.append(it["evidence_id"])

    answer = (
        "Наблюдения: " + "; ".join(obs) + ". "
        "Вероятные причины: признаки указывают на локальное изменение режима в перечисленных объектах; "
        "уверенность средняя, так как расчёт не заменяет натурную проверку. "
        "Что проверить: состояние арматуры и фактическое сопротивление участков в зоне отклонений, "
        "соответствие фактических расходов и давлений расчётным. "
        "Рекомендации: обследовать зону отклонений и уточнить модель по результатам измерений. "
        + LIMITATIONS
    )
    label_guess = scen["truth"].get("primary_fault") or "no_problem"
    per_case = {}
    for cid in case_ids:
        fp = common.ROOT / "data" / "cases" / "pending" / f"{cid}.json"
        if not fp.exists():
            continue
        mode = common.read_json(fp)["mode"]
        entry = {"observations": obs, "checks": ["Проверить фактическое сопротивление и арматуру в зоне отклонений.",
                                                 "Сверить расчётные расходы/давления с измерениями."],
                 "recommendations": ["Обследовать зону отклонений и уточнить модель по измерениям."],
                 "limitations": [LIMITATIONS],
                 "probable_causes": [{"text": "Локальное изменение режима в перечисленных объектах",
                                      "confidence": "medium", "check": "check_roughness"}],
                 "answer": answer}
        if mode == "make_report":
            entry["report_markdown"] = REPORT_HEADER.format(
                ctx=f"Сеть {scen['network_id']}, суточный расчёт; сравнение с базовым сценарием.",
                res="; ".join(obs[:3]),
                prob="; ".join(o.split(' (')[0] for o in obs[:4]),
                cause="Наиболее вероятно — локальное изменение режима в перечисленных объектах (уверенность средняя).",
                rec="Обследовать зону отклонений; уточнить модель по результатам измерений.",
                lim=LIMITATIONS)
        per_case[cid] = entry
    payload = {
        "cases": per_case,
        "label": {
            "has_problem": bool(scen["truth"]["is_faulted"]),
            "category": label_guess if label_guess != "high_velocity" else "high_velocity",
            "severity": scen["truth"].get("fault_severity") or "info",
            "confidence": "medium",
            "primary_objects": sorted({a["object"] for a in top if a["object"] != "network"})[:3],
            "evidence_refs": refs[:8],
            "likely_cause": "Автотест конвейера: конкретная причина не формулируется.",
        },
        "_case_ids": case_ids,
        "probes": {"observations": "; ".join(obs[:2]) or "нет данных",
                   "causes": "требуется проверка на сети (автотест)",
                   "limitations": LIMITATIONS},
        "free": [{"question": "Какие допущения расчёта сильнее всего влияют на вывод?",
                  "answer": "На результат влияют модельные суточные графики водопотребления и паспортная "
                            "характеристика насоса; эти допущения одинаковы во всех сценариях сети (автотест)."}],
        "time_spent_min": 15,
        "review_comments": "Автоматическая тестовая разметка конвейера.",
        "_double": False,
    }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Автотест конвейера разметки")
    ap.add_argument("--batch", default="data/batches/batch_exp_01_01.json")
    ap.add_argument("--expert", default="pipeline_test")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    batch = common.read_json(common.ROOT / args.batch)
    cases_by_scen: dict[str, list[str]] = {sid: [] for sid in batch["scenario_ids"]}
    for cid in batch["case_ids"]:
        for sid in batch["scenario_ids"]:
            if cid.startswith(f"c_{sid}__"):
                cases_by_scen[sid].append(cid)
    scenarios = {sid: make_payload(sid, cases_by_scen[sid]) for sid in batch["scenario_ids"]}
    export = {
        "batch_id": batch["batch_id"], "expert_id": args.expert,
        "exported_at": common.now_iso(), "schema": "expert-pack-1.0",
        "scenarios": scenarios,
    }
    out = common.ROOT / (args.out or f"data/cases/inbox/{batch['batch_id']}__{args.expert}.json")
    common.write_json(out, export)
    print(f"Автотестовая выгрузка → {out.relative_to(common.ROOT)} "
          f"({len(scenarios)} сценариев)")


if __name__ == "__main__":
    main()
