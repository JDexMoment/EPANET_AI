"""Этап 7 — LLM Interpretation: подключаемый интерфейс модели (vLLM / llama.cpp / API / offline stub)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from aquabit_ai.config.jsonl_schemas import (
    InlineFactsBundle,
    InterpretationTarget,
    TrainingManifestSummary,
)
from aquabit_ai.config.manifest import ExecutionMode


SYSTEM_PROMPT_VERSION = "v1.0"


@runtime_checkable
class LLMBackend(Protocol):
    """Протокол подключаемого LLM-провайдера (ADR-0005)."""

    model_id: str
    prompt_version: str

    def interpret(
        self,
        facts_inline: InlineFactsBundle,
        manifest: TrainingManifestSummary,
        mode: ExecutionMode,
        error_feedback: str | None = None,
    ) -> InterpretationTarget:
        """Формирует структурированную инженерную интерпретацию строго по предоставленным фактам."""
        ...


__all__ = ["LLMBackend", "SYSTEM_PROMPT_VERSION"]
