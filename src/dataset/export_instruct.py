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


def _read_context(ref: str | None) -> tuple[str, bool]:
    """Текст контекста для модели. Ищем в нескольких местах, чтобы работали и кейсы
    из внутреннего конвейера (data/scenarios/...), и выгрузки сервиса (data/collected/...)."""
    if not ref:
        return "{}", False
    for base in (common.ROOT, common.ROOT / "data" / "collected", common.ROOT / "data"):
        cand = base / ref
        if cand.exists():
            return cand.read_text(encoding="utf-8"), True
    return "{}", False


SYNTHETIC_SOURCES = {"pipeline_test", "synthetic_example", "synthetic_demo"}
SYNTHETIC_ANNOTATORS = {"pipeline_test", "synthetic", "demo"}


def _is_synthetic(case: dict) -> bool:
    """Синтетический ли кейс: автотест конвейера или образец формата.

    Правило проекта: обучаемся только на реальных данных. Синтетика допускается
    лишь в тестах и в осознанной аугментации (тогда экспорт запускается с флагом).
    """
    ann = case.get("annotation") or {}
    if (ann.get("source") or "").lower() in SYNTHETIC_SOURCES:
        return True
    if (ann.get("annotator_id") or "").lower() in SYNTHETIC_ANNOTATORS:
        return True
    if "synthetic" in (ann.get("note") or "").lower():
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Экспорт SFT-датасета")
    ap.add_argument("--dir", default="data/cases/filled")
    ap.add_argument("--out", default="data/splits")
    ap.add_argument("--include-drafts", action="store_true", help="включать невалидированные кейсы")
    ap.add_argument("--include-synthetic", action="store_true",
                    help="разрешить синтетические кейсы (pipeline_test, образцы формата). "
                         "По умолчанию они НЕ попадают в датасет обучения")
    ap.add_argument("--include-candidates", action="store_true",
                    help="включать кейсы со статусом candidate (собранные сервисом разметки, "
                         "ещё не прошедшие ревью ведущего инженера)")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/dataset.yaml")
    ratios = cfg["splits"]["ratios"]
    src = common.ROOT / args.dir
    if not src.exists() or not list(src.glob("c_*.json")):
        print("=" * 78)
        print(f"Экспорт датасета: в {src.relative_to(common.ROOT)} нет размеченных кейсов")
        print("=" * 78)
        print("  Датасет собирается только из реальных данных:")
        print("   • разметка инженеров через сервис → data/collected/cases (docs/10_COLLECTION_SERVICE.md)")
        print("   • внутренняя разметка → data/cases/filled/")
        print("  Пустые файлы сплитов не создаю, чтобы не путать состояние репозитория.")
        return
    out_dir = common.ensure_dir(common.ROOT / args.out)
    system = SYSTEM_PROMPT.read_text(encoding="utf-8")

    buckets: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    structured_rows, eval_rows = [], []
    skipped = 0
    skipped_synthetic = 0
    ctx_missing = 0

    for fp in sorted(src.glob("c_*.json")):
        case = common.read_json(fp)
        if _is_synthetic(case) and not args.include_synthetic:
            skipped_synthetic += 1
            continue
        gold = (case.get("gold") or {}).get("answer")
        if not gold:
            skipped += 1
            continue
        status = (case.get("annotation") or {}).get("review_status")
        allowed = {"submitted", "accepted"}
        if args.include_candidates:
            allowed.add("candidate")
        if not args.include_drafts and status not in allowed:
            skipped += 1
            continue

        ref = case["facts"].get("llm_context_ref")
        ctx_text, ctx_found = _read_context(ref)
        if not ctx_found:
            ctx_missing += 1

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
    if ctx_missing:
        print(f"ВНИМАНИЕ: у {ctx_missing} кейсов не найден файл контекста (llm_context_ref) — "
              f"такие примеры уйдут с пустым контекстом. Проверьте, что архив распакован "
              f"через tools/pull_collected.py и каталог contexts/ на месте.")
    if skipped_synthetic:
        print(f"отсечено синтетических кейсов: {skipped_synthetic} "
              f"(проект обучается только на реальных данных; включить — флаг --include-synthetic)")
    print(f"→ {out_dir}")


if __name__ == "__main__":
    main()
