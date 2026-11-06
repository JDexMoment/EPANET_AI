"""Пакет генерации JSONL-корпуса и дистилляции знаний Учитель -> Ученик (Teacher -> Student Distillation)."""

from __future__ import annotations

from aquabit_ai.jsonl.distiller import (
    TEACHER_SYSTEM_PROMPT,
    DistillationOutcome,
    DistillationTaskPrompt,
    call_openai_compatible_teacher,
    distill_with_teacher_and_verify,
    generate_diverse_teacher_prompts,
    strip_thinking_blocks,
    verify_response_numbers,
)

__all__ = [
    "TEACHER_SYSTEM_PROMPT",
    "DistillationOutcome",
    "DistillationTaskPrompt",
    "call_openai_compatible_teacher",
    "distill_with_teacher_and_verify",
    "generate_diverse_teacher_prompts",
    "strip_thinking_blocks",
    "verify_response_numbers",
]
