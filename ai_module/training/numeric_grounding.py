"""Shared numeric-grounding helpers for dataset validation and benchmarking.

Implements the zero-hallucination gate (Roadmap Section 10 & 12):
every numeric claim in a model answer must be traceable to
  (a) a number present in the machine-readable context,
  (b) a normative threshold constant,
  (c) a structural/version constant, or
  (d) an exact arithmetic delta of two context numbers.
"""

import re
from typing import List, Set

from ai_module.config.settings import DEFAULT_THRESHOLDS

ALLOWED_STRUCTURAL_NUMBERS: Set[str] = {
    "2.2",       # EPANET 2.2 version string
    "2.2.0",
    "0.0", "1.0",
    "15.0", "10.0", "60.0", "75.0",
    "2.5", "3.5", "0.05",
    "100",       # percent / rounding base
    "1000",      # m->km / mm->m conversion base
}

# Russian engineering keywords -> canonical anomaly categories
CATEGORY_KEYWORDS = {
    "low_pressure": ["низкий свободный напор", "пониженный свободный напор", "низкий напор"],
    "negative_pressure": ["отрицательное давление", "вакуум", "вакуумирование"],
    "high_pressure": ["избыточное давление", "высокое давление", "критически высокое давление"],
    "high_velocity": ["скорост", "превышение допустимой скорости", "повышенная скорость"],
    "high_headloss_gradient": ["уклон", "гидравлический уклон", "потери напора"],
    "stagnation_zero_flow": ["застой", "скорости движения воды", "нулевой скорост"],
    "normal_operation": ["нарушений не выявлено", "в пределах допустимых", "норм"],
    "scenario_comparison": ["сравнение сценариев", "delta", "δ"],
}


def extract_numbers(text: str) -> List[str]:
    return re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])", text)


def allowed_numbers(context_text: str, include_deltas: bool = True) -> Set[str]:
    allowed: Set[str] = set(extract_numbers(context_text))

    for v in DEFAULT_THRESHOLDS.values():
        fv = float(v)
        allowed.add(f"{fv}")
        allowed.add(f"{fv:.1f}")
        allowed.add(f"{fv:.2f}")

    allowed |= ALLOWED_STRUCTURAL_NUMBERS

    if include_deltas:
        allowed |= derived_deltas(allowed)
    return allowed


def derived_deltas(numbers: Set[str]) -> Set[str]:
    floats = sorted({float(x) for x in numbers if re.fullmatch(r"\d+(?:\.\d+)?", x)})
    deltas: Set[str] = set()
    if len(floats) > 400:
        return deltas
    for i, a in enumerate(floats):
        for b in floats[i:]:
            d = abs(a - b)
            if d == 0:
                continue
            deltas.add(f"{d}")
            deltas.add(f"{d:.1f}")
            deltas.add(f"{d:.2f}")
            deltas.add(f"{d:.3f}")
    return deltas


def unverified_numbers(answer: str, context_text: str) -> List[str]:
    """Returns numeric claims in `answer` that cannot be grounded in `context_text`."""
    allowed = allowed_numbers(context_text)
    bad: List[str] = []
    for n in extract_numbers(answer):
        if n in allowed:
            continue
        f = float(n)
        if f"{f:.1f}" in allowed or f"{f:.2f}" in allowed or f"{f:.3f}" in allowed:
            continue
        bad.append(n)
    return sorted(set(bad))


def detect_categories(text: str) -> Set[str]:
    low = text.lower()
    found: Set[str] = set()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in low for k in kws):
            found.add(cat)
    return found
