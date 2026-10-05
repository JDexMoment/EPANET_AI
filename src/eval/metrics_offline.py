"""Метрики ДО обучения: что вообще есть в датасете.

Показывает, достаточно ли разнообразия, нет ли перекосов и «пустых» кейсов,
готовы ли данные к fine-tuning.

Запуск:
    python -m src.eval.metrics_offline
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .. import common

TARGETS = {   # ориентиры (roadmap п.9)
    "cases_prototype": (200, 500),
    "cases_finetune": (1000, 5000),
    "scenarios_min": (20, 30),
}


def main() -> None:
    cfg = common.load_yaml("configs/dataset.yaml")
    manifest = common.read_jsonl("data/scenarios/manifest.jsonl")
    scenarios = [m for m in manifest if m.get("status") == "ok"]

    filled_dir = common.ROOT / "data" / "cases" / "filled"
    pending_dir = common.ROOT / "data" / "cases" / "pending"
    cases = [common.read_json(p) for p in sorted((filled_dir if filled_dir.exists() else pending_dir).glob("c_*.json"))]
    filled = [c for c in cases if (c["gold"] or {}).get("answer")]

    # разнообразие сценариев: по типу внесённой неисправности
    by_fault, by_visibility = Counter(), Counter()
    for m in scenarios:
        sdir = common.ROOT / "data" / "scenarios" / m["scenario_id"]
        scen = common.read_json(sdir / "scenario.json")
        d = common.read_json(sdir / "derived" / "derived_metrics.json")
        fault = scen["truth"].get("primary_fault") or "baseline"
        by_fault[fault] += 1
        vis = d.get("observability", {}).get("visible_effect")
        by_visibility["видимый эффект" if vis else "слабый/нет эффекта"] += 1

    # покрытие по режимам и категориям
    modes = Counter(c["mode"] for c in cases)
    cats = Counter((c["label"] or {}).get("category") or "не размечено" for c in filled)
    sev = Counter((c["label"] or {}).get("severity") or "не размечено" for c in filled)

    # проверка «кейс ↔ сценарий»: нет ли кейсов без сценария
    known = {m["scenario_id"] for m in scenarios}
    orphan = [c["case_id"] for c in cases if c["scenario_id"] not in known]

    print("=" * 78)
    print("ДАТАСЕТ EPANET-AI: состояние")
    print("=" * 78)
    print(f"сценариев (ok): {len(scenarios)}   цель Этапа 1: {TARGETS['scenarios_min'][0]}–{TARGETS['scenarios_min'][1]}")
    print(f"кейсов всего:   {len(cases)}   из них заполнено: {len(filled)}")
    print(f"прототип: {TARGETS['cases_prototype'][0]}–{TARGETS['cases_prototype'][1]} кейсов · "
          f"fine-tuning: {TARGETS['cases_finetune'][0]}–{TARGETS['cases_finetune'][1]}")
    print(f"целевое разбиение: {cfg['splits']['ratios']} по сценариям (strategy={cfg['splits']['strategy']})")
    print("\n-- сценарии по типу неисправности --")
    for k, v in by_fault.most_common():
        print(f"   {k:26s} {v}")
    print("\n-- наблюдаемость эффекта --")
    for k, v in by_visibility.items():
        print(f"   {k:26s} {v}")
    print("\n-- кейсы по режимам --")
    for k, v in modes.most_common():
        print(f"   {k:26s} {v}")
    if filled:
        print("\n-- заполненные кейсы по категориям --")
        for k, v in cats.most_common():
            print(f"   {k:26s} {v}")
        print("\n-- по severity --")
        for k, v in sev.most_common():
            print(f"   {k:26s} {v}")
    if orphan:
        print(f"\n!! кейсы без сценария: {len(orphan)} (пример: {orphan[0]})")

    # вердикт
    n = len(filled) if filled else len(cases)
    verdict = ("прототип" if n < TARGETS["cases_prototype"][0] else
               "fine-tuning (минимум)" if n < TARGETS["cases_finetune"][0] else "fine-tuning (устойчиво)")
    print("\n" + "=" * 78)
    print(f"ВЕРДИКТ: {n} кейсов → уровень «{verdict}»")
    if not filled:
        print("Кейсы ещё не размечены: заполненные данные появятся в data/cases/filled/.")
    print("=" * 78)


if __name__ == "__main__":
    main()
