"""Самопроверка ответа инженера прямо в форме: числа, ссылки E-xxx, длина.

Использует те же правила, что и validate_cases.py при приёмке датасета, чтобы инженер
не узнавал об ошибках через сутки, а видел их сразу под полем ответа.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.dataset.validate_cases import CLEAN_ID, EVID_RE, NUM_RE, _evidence_numbers
    _VALIDATOR = True
except Exception:  # noqa: BLE001
    _VALIDATOR = False
    CLEAN_ID = re.compile(r"[A-Za-zА-Яа-я]{1,4}-?\d+")
    NUM_RE = re.compile(r"[-−+]?\d+(?:[.,]\d+)?")
    EVID_RE = re.compile(r"\bE-\d{3,}\b")

    def _evidence_numbers(evidence: list[dict], ctx_text: str = "") -> set[str]:
        return set()

MIN_WORDS = 80          # как в ТЗ инженерам и в правилах датасета
MAX_WORDS = 450


def _nums(text: str, only_significant: bool = False) -> set[str]:
    """Числа в тексте.

    only_significant=True отбрасывает «бытовые» целые (1–9 без десятичной части):
    они почти всегда означают «несколько шагов», «2–3 м запаса» и дают ложные срабатывания.
    Значимыми считаются числа с десятичной частью и значения ≥ 10.
    """
    cleaned = CLEAN_ID.sub(" ", text or "")
    out = set()
    for m in NUM_RE.finditer(cleaned):
        raw = m.group(0).replace("−", "-").replace(",", ".")
        try:
            val = abs(float(raw))
        except ValueError:
            continue
        if only_significant and val < 10 and "." not in raw:
            continue
        out.add(f"{val:.3f}".rstrip("0").rstrip("."))
    return out


def check_answer(answer: str, evidence: dict | list, context_text: str = "") -> dict:
    """Возвращает отчёт самопроверки для интерфейса инженера."""
    ev_list = list(evidence.values()) if isinstance(evidence, dict) else list(evidence or [])
    allowed = _evidence_numbers(ev_list, context_text) if _VALIDATOR else set()
    # дополнительно разрешаем числа, которые видны в контексте модели
    allowed |= _nums(context_text)

    used = _nums(answer, only_significant=True)
    unknown = sorted(n for n in used if n not in allowed)
    refs = sorted(set(EVID_RE.findall(answer or "")))
    known_ids = {e.get("evidence_id") for e in ev_list}
    bad_refs = [r for r in refs if r not in known_ids]

    words = len((answer or "").split())
    issues: list[str] = []
    if unknown:
        issues.append("есть числа, не подтверждённые данными расчёта: " + ", ".join(unknown[:8])
                      + " (проверяются значения ≥ 10 и числа с десятичной частью)")
    if bad_refs:
        issues.append("ссылки на несуществующие факты: " + ", ".join(bad_refs[:8]))
    if words and words < MIN_WORDS:
        issues.append(f"ответ короткий: {words} слов (рекомендуется ≥ {MIN_WORDS})")
    if words > MAX_WORDS:
        issues.append(f"ответ слишком длинный: {words} слов (рекомендуется ≤ {MAX_WORDS})")
    if not refs and words >= MIN_WORDS:
        issues.append("нет ни одной ссылки (E-xxx) — добавьте ссылки на факты")

    return {
        "ok": not issues,
        "issues": issues,
        "words": words,
        "numbers_total": len(used),
        "numbers_unknown": unknown[:20],
        "evidence_refs": refs,
        "evidence_refs_bad": bad_refs,
        "evidence_available": sorted(known_ids),
    }
