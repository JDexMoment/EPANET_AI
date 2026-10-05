"""Экспорт датасета в форматы обучения.

Выход:
  data/splits/train.jsonl, val.jsonl, test.jsonl — SFT (chat-формат);
  data/splits/structured.jsonl                  — вариант с ответом-в-JSON;
  data/splits/eval_test.jsonl                   — кейсы для бенчмарка модели
                                                  (с required_facts/forbidden_claims).

Разбиение — ПО СЦЕНАРИЯМ (в train/val/test не попадают кейсы одного расчёта),
иначе модель просто запомнит конкретную сеть.

Запуск:
    python -m src.dataset.export_instruct
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .. import common

SYSTEM_PROMPT = common.ROOT / "src" / "prompt_templates" / "system_ru.md"


def _bucket(scenario_id: str, ratios: dict) -> str:
    h = int(hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    if h < ratios["train"]:
        return "train"
    if h < ratios["train"] + ratios["val"]:
        return "val"
    return "test"


def build_user_turn(case: dict, ctx_text: str) -> str:
    return (
        "### КОНТЕКСТ РАСЧЁТА EPANET (JSON, сокращённый, единицы внутри)\n"
        f"{ctx_text}\n\n"
        "### ЗАПРОС ПОЛЬЗОВАТЕЛЯ\n"
        f"{case['question']}\n\n"
        "Ответьте по правилам: наблюдения → вероятные причины (с уверенностью) → что проверить → "
        "рекомендации → ограничения. Каждое число — со ссылкой на evidence (E-xxx). Не выдумывайте данные."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Экспорт SFT-датасета")
    ap.add_argument("--dir", default="data/cases/filled")
    ap.add_argument("--out", default="data/splits")
    ap.add_argument("--include-drafts", action="store_true", help="включать невалидированные кейсы")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/dataset.yaml")
    ratios = cfg["splits"]["ratios"]
    src = common.ROOT / args.dir
    out_dir = common.ensure_dir(common.ROOT / args.out)
    system = SYSTEM_PROMPT.read_text(encoding="utf-8")

    buckets: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    structured_rows, eval_rows = [], []
    skipped = 0

    for fp in sorted(src.glob("c_*.json")):
        case = common.read_json(fp)
        gold = (case.get("gold") or {}).get("answer")
        if not gold:
            skipped += 1
            continue
        if not args.include_drafts and (case.get("annotation") or {}).get("review_status") not in ("submitted", "accepted"):
            skipped += 1
            continue

        ref = case["facts"].get("llm_context_ref")
        ctx_text = (common.ROOT / ref).read_text(encoding="utf-8") if ref and (common.ROOT / ref).exists() else "{}"

        row = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": build_user_turn(case, ctx_text)},
                {"role": "assistant", "content": gold.strip()},
            ],
            "meta": {"case_id": case["case_id"], "scenario_id": case["scenario_id"],
                     "mode": case["mode"], "category": case["label"].get("category"),
                     "severity": case["label"].get("severity")},
        }
        buckets[_bucket(case["scenario_id"], ratios)].append(row)

        structured = (case["gold"] or {}).get("answer_structured")
        if structured and any(structured.values()):
            structured_rows.append({
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": build_user_turn(case, ctx_text)},
                    {"role": "assistant", "content": json.dumps(structured, ensure_ascii=False)},
                ],
                "meta": row["meta"],
            })

        if _bucket(case["scenario_id"], ratios) == "test" or (case.get("eval") or {}).get("required_facts"):
            eval_rows.append({
                "case_id": case["case_id"], "mode": case["mode"], "question": case["question"],
                "context": ctx_text, "reference_answer": gold,
                "label": case["label"], "required_facts": case["eval"].get("required_facts", []),
                "forbidden_claims": case["eval"].get("forbidden_claims", []),
            })

    for name, rows in buckets.items():
        common.write_jsonl(out_dir / f"{name}.jsonl", rows)
        print(f"{name}.jsonl: {len(rows)} примеров")
    common.write_jsonl(out_dir / "structured.jsonl", structured_rows)
    common.write_jsonl(out_dir / "eval_test.jsonl", eval_rows)
    print(f"structured.jsonl: {len(structured_rows)}, eval_test.jsonl: {len(eval_rows)}, "
          f"пропущено (не заполнено): {skipped}")
    print(f"→ {out_dir}")


if __name__ == "__main__":
    main()
