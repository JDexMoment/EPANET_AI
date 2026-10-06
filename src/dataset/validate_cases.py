"""Валидация заполненных кейсов перед обучением.

Проверяет:
  1. соответствие схеме schemas/case.schema.json;
  2. заполненность обязательных полей (label + gold.answer);
  3. что все ссылки E-xxx в ответах есть в evidence этого кейса;
  4. что каждое число в золотом ответе подтверждается evidence
     (главный контроль против «выдуманных» чисел в датасете);
  5. длину ответа и лимиты из configs/dataset.yaml.

Запуск:
    python -m src.dataset.validate_cases --dir data/cases/filled
    python -m src.dataset.validate_cases --dir data/cases/filled
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .. import common

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    HAS_JSONSCHEMA = False

CLEAN_ID = re.compile(r"[A-Za-zА-Яа-я]{1,4}-?\d+")          # J-105, P-106, E-007, PU-1 …
NUM_RE = re.compile(r"[-−+]?\d+(?:[.,]\d+)?")              # числа, в т.ч. отрицательные
EVID_RE = re.compile(r"\bE-\d{3,}\b")                       # ссылки на факты

# числа, которые не нужно подтверждать evidence (время суток, индексы, диапазоны лет)
IGNORE_NUMBERS = {str(i) for i in range(0, 25)} | {"1", "2", "3", "5", "10", "15", "20", "30", "60", "100"}


def _nums(text: str) -> set[str]:
    """Все числа из текста. Идентификаторы (J-105, E-007) предварительно вырезаются."""
    cleaned = CLEAN_ID.sub(" ", text or "")
    out = set()
    for m in NUM_RE.finditer(cleaned):
        v = m.group(0).replace(",", ".").replace("−", "-").replace("+", "")
        try:
            out.add(f"{float(v):g}")
        except ValueError:
            continue
    return out


def _evidence_numbers(evidence: list[dict], ctx_text: str) -> set[str]:
    """Все числа, которые «легальны»: из evidence и из самого контекста."""
    nums: set[str] = set()
    for e in evidence:
        for k in ("value", "time_h"):
            if isinstance(e.get(k), (int, float)):
                nums.add(f"{float(e[k]):g}")
        nums |= _nums(e.get("statement", ""))
    nums |= _nums(ctx_text)
    return nums


def validate_case(case: dict, cfg: dict, ctx_text: str = "") -> dict:
    res = {"case_id": case.get("case_id"), "errors": [], "warnings": []}

    # 1. схема
    if HAS_JSONSCHEMA:
        schema = common.read_json("schemas/case.schema.json")
        try:
            jsonschema.validate(case, schema)
        except jsonschema.ValidationError as e:  # noqa: F841
            res["errors"].append(f"схема: {e.message[:200]}")
    else:
        res["warnings"].append("jsonschema не установлен — проверка схемы пропущена")

    label = case.get("label") or {}
    gold = case.get("gold") or {}
    answer = (gold.get("answer") or "").strip()
    structured = gold.get("answer_structured") or {}

    # 2. заполненность
    if label.get("has_problem") is None:
        res["errors"].append("label.has_problem не заполнен")
    if not label.get("category"):
        res["errors"].append("label.category не заполнен")
    if not label.get("severity"):
        res["errors"].append("label.severity не заполнен")
    if not label.get("confidence"):
        res["errors"].append("label.confidence не заполнен")
    if not answer and not (gold.get("report_markdown") or "").strip():
        res["errors"].append("нет gold.answer (или report_markdown для режима отчёта)")

    # 3. ссылки на evidence
    ev_ids = {e["evidence_id"] for e in case["facts"]["evidence"]}
    cited = set(EVID_RE.findall(answer + " " + json.dumps(structured, ensure_ascii=False)))
    unknown = cited - ev_ids
    if unknown:
        res["errors"].append(f"ссылки на отсутствующие факты: {sorted(unknown)}")
    if answer and not cited and case.get("mode") != "ask":
        res["errors"].append("в ответе нет ни одной ссылки E-xxx")
    if answer and not cited and case.get("mode") == "ask" and _nums(answer):
        res["warnings"].append("в ask-ответе есть числа, но нет ссылок E-xxx")

    # 4. числа: каждое должно подтверждаться evidence/контекстом
    if answer:
        allowed = _evidence_numbers(case["facts"]["evidence"], ctx_text)
        allowed_f = sorted({abs(float(x)) for x in allowed})   # знак часто выражен словами («снизилось на …»)
        hard = []
        for n in _nums(answer):
            if n in IGNORE_NUMBERS:
                continue
            f = float(n)
            if not any(abs(abs(f) - a) <= max(0.5, 0.1 * a) for a in allowed_f):
                hard.append(n)
        if hard:
            res["warnings"].append(f"числа без подтверждения в evidence: {sorted(hard)[:10]}")

    # 5. длина
    if answer:
        words = len(answer.split())
        lo, hi = cfg["validation"]["min_gold_words"], cfg["validation"]["max_gold_words"]
        if words < lo:
            res["warnings"].append(f"ответ короткий: {words} слов (< {lo})")
        if words > hi:
            res["warnings"].append(f"ответ длинный: {words} слов (> {hi})")

    res["status"] = "accepted" if not res["errors"] else "needs_fix"
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Валидация кейсов")
    ap.add_argument("--dir", default="data/cases/filled")
    ap.add_argument("--report", default="data/eval/validation_report.json")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/dataset.yaml")
    cdir = common.ROOT / args.dir
    files = sorted(cdir.glob("c_*.json"))
    if not files:
        print(f"Нет кейсов в {cdir}")
        return

    reports, n_ok, n_fix = [], 0, 0
    for fp in files:
        case = common.read_json(fp)
        ctx_text = ""
        ref = case.get("facts", {}).get("llm_context_ref")
        if ref and (common.ROOT / ref).exists():
            ctx_text = (common.ROOT / ref).read_text(encoding="utf-8")
        r = validate_case(case, cfg, ctx_text)
        reports.append(r)
        if r["status"] == "accepted":
            n_ok += 1
        else:
            n_fix += 1
            print(f"✗ {r['case_id']}: " + "; ".join(r["errors"]))
        for w in r["warnings"]:
            print(f"  ~ {r['case_id']}: {w}")

    common.write_json(args.report, reports)
    print(f"\nПринято: {n_ok}, требуют правок: {n_fix} (всего {len(files)})")
    print(f"Отчёт → {args.report}")


if __name__ == "__main__":
    main()
