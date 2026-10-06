"""Понимание экрана: скриншот → структурированный JSON.

Решение из обсуждения: НЕ обучаем CV/VLM-модель. Нужно лишь надёжно определить,
что находится на экране (тип экрана, выбранный объект, шаг времени, видимые
числа), и передать это обычной текстовой LLM вместе с контекстом расчёта.
Пиксели в LLM не уходят — уходят только факты об экране.
"""
from __future__ import annotations

SCREEN_TYPES = ["map", "results_table", "object_editor", "time_series",
                "report", "form", "dialog", "unknown"]
AMBIGUITY_LEVELS = ["low", "medium", "high"]


def validate(det: dict) -> list[str]:
    """Возвращает список ошибок (пустой — всё хорошо)."""
    errs: list[str] = []

    def need(field: str) -> bool:
        if field not in det or det[field] is None:
            errs.append(f"нет обязательного поля {field}")
            return False
        return True

    for f in ("schema_version", "app", "screen_type", "confidence", "panels", "ambiguity", "ui_context"):
        if not need(f):
            continue

    if det.get("screen_type") not in SCREEN_TYPES:
        errs.append(f"screen_type={det.get('screen_type')!r} не из {SCREEN_TYPES}")

    conf = det.get("confidence")
    if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
        errs.append(f"confidence={conf!r} должно быть числом 0..1")

    amb = det.get("ambiguity") or {}
    if amb.get("level") not in AMBIGUITY_LEVELS:
        errs.append(f"ambiguity.level={amb.get('level')!r} не из {AMBIGUITY_LEVELS}")

    so = det.get("selected_object")
    if so is not None and (not isinstance(so, dict) or not so.get("id")):
        errs.append("selected_object должен быть null или объектом с полем id")

    for i, vo in enumerate(det.get("visible_objects") or []):
        if not isinstance(vo, dict) or not vo.get("id"):
            errs.append(f"visible_objects[{i}] без id")

    for i, a in enumerate(det.get("actions") or []):
        if not isinstance(a, dict) or not a.get("intent"):
            errs.append(f"actions[{i}] без intent")

    if not isinstance(det.get("panels"), list):
        errs.append("panels должен быть списком")

    return errs
