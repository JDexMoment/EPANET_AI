"""Pydantic-схемы потоков facts.jsonl, training.jsonl и predictions.jsonl (§1, §5, §6)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from aquabit_ai.config.manifest import ExecutionMode


SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class FactSource(BaseModel):
    """Обязательная трассировка происхождения факта (§1.4, §5)."""

    model_config = ConfigDict(extra="allow")

    file: StrictStr | None = None
    field: StrictStr | None = None
    aggregation: StrictStr | None = None
    filter: dict[str, StrictStr] | None = None
    n_steps: int | None = Field(default=None, ge=0)
    comparison: StrictStr | None = None
    step_h: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _ensure_non_empty_source(self) -> "FactSource":
        if not self.file and not self.aggregation:
            raise ValueError(
                "FactSource обязан содержать хотя бы 'file' или 'aggregation' для трассируемости"
            )
        return self


class FactQuality(BaseModel):
    """Флаги качества нормализованного значения (§3.9, §5)."""

    model_config = ConfigDict(extra="forbid")

    is_null: bool = False
    is_zero: bool = False
    is_outlier: bool | None = None
    is_out_of_range: bool = False
    unit_converted: bool = False
    timestamp_gap: bool = False


class TracedFact(BaseModel):
    """Единичный факт с трассируемостью и единицей измерения (§5, §6.1)."""

    model_config = ConfigDict(extra="forbid")

    value: float | int | StrictStr | bool | dict[str, Any] | None = None
    unit: StrictStr | None = None
    source: FactSource
    quality: FactQuality | None = None

    @model_validator(mode="after")
    def _validate_null_and_unit_rules(self) -> "TracedFact":
        if self.quality is not None and self.quality.is_null and self.value is not None:
            raise ValueError(
                "При quality.is_null=True поле value обязано быть null/отсутствовать (§6.1)"
            )
        is_numeric_scalar = isinstance(self.value, (int, float)) and not isinstance(self.value, bool)
        if is_numeric_scalar and (self.unit is None or not self.unit.strip()):
            raise ValueError(
                f"Числовой факт value={self.value!r} обязан иметь непустое поле unit (§1.8)"
            )
        return self


class FactsJsonlRecord(BaseModel):
    """Строка потока facts.jsonl (§6.1)."""

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["object", "system", "fact"]
    run_id: StrictStr = Field(..., min_length=1)
    object_type: StrictStr | None = None
    object_id: StrictStr | None = None
    object_name: StrictStr | None = None
    mode: ExecutionMode
    facts: dict[str, TracedFact]

    @field_validator("facts")
    @classmethod
    def _check_snake_case_keys(cls, v: dict[str, TracedFact]) -> dict[str, TracedFact]:
        for key in v:
            if not SNAKE_CASE_RE.match(key):
                raise ValueError(f"Ключ факта '{key}' обязан быть в snake_case (§6.1)")
        return v

    @model_validator(mode="after")
    def _check_record_type_constraints(self) -> "FactsJsonlRecord":
        if self.record_type in {"object", "fact"}:
            if not self.object_type or not self.object_id:
                raise ValueError(
                    f"Для record_type='{self.record_type}' поля object_type и object_id (str) обязательны"
                )
        if self.record_type == "fact" and len(self.facts) != 1:
            raise ValueError("Для record_type='fact' словарь facts должен содержать ровно 1 факт")
        return self


class CriticalIssueItem(BaseModel):
    """Элемент списка критических проблем в ответе учителя/студента (§6.2, §7)."""

    model_config = ConfigDict(extra="allow")

    object_id: StrictStr = Field(..., min_length=1)
    object_name: StrictStr | None = None
    issue: StrictStr = Field(..., min_length=1)
    source: StrictStr = Field(..., min_length=1)


class RecommendationItem(BaseModel):
    """Инженерная рекомендация со ссылкой на факт (§6.2, §7)."""

    model_config = ConfigDict(extra="forbid")

    text: StrictStr = Field(..., min_length=1)
    source: StrictStr = Field(..., min_length=1)


class InterpretationTarget(BaseModel):
    """Структура ответа модели (target в training.jsonl / prediction в predictions.jsonl)."""

    model_config = ConfigDict(extra="forbid")

    summary: StrictStr = Field(..., min_length=1)
    critical_issues: list[CriticalIssueItem] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    limitations: list[StrictStr] = Field(default_factory=list)


class InlineEntityFacts(BaseModel):
    """Компактное представление объекта в facts_inline внутри training.jsonl."""

    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(..., min_length=1)
    name: StrictStr | None = None
    facts: dict[str, TracedFact]


class InlineFactsBundle(BaseModel):
    """Полный срез фактов расчёта в training.jsonl (§6.2)."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[InlineEntityFacts] = Field(default_factory=list)
    pipes: list[InlineEntityFacts] = Field(default_factory=list)
    pumps: list[InlineEntityFacts] = Field(default_factory=list)
    reservoirs: list[InlineEntityFacts] = Field(default_factory=list)
    valves: list[InlineEntityFacts] = Field(default_factory=list)
    sources: list[InlineEntityFacts] = Field(default_factory=list)
    system: dict[str, TracedFact] = Field(default_factory=dict)


class TrainingPeriodSummary(BaseModel):
    """Краткая сводка периода в training.jsonl (§6.2)."""

    model_config = ConfigDict(extra="forbid")

    start: StrictStr
    end: StrictStr
    step_s: int = Field(..., gt=0)
    n_steps: int = Field(..., ge=1)


class TrainingManifestSummary(BaseModel):
    """Краткая сводка манифеста в training.jsonl (§6.2)."""

    model_config = ConfigDict(extra="allow")

    model_id: StrictStr
    scenario_id: StrictStr
    period: TrainingPeriodSummary
    method: StrictStr | None = None
    converged: bool | None = None


class TrainingJsonlRecord(BaseModel):
    """Строка корпуса дистилляции training.jsonl (§6.2)."""

    model_config = ConfigDict(extra="forbid")

    example_id: StrictStr = Field(..., min_length=1)
    run_id: StrictStr = Field(..., min_length=1)
    mode: ExecutionMode
    manifest: TrainingManifestSummary
    facts_ref: StrictStr = Field(..., min_length=1)
    facts_inline: InlineFactsBundle
    charts_ref: dict[str, StrictStr | list[StrictStr]] = Field(default_factory=dict)
    reference_report_blocks: dict[str, StrictStr] = Field(default_factory=dict)
    target: InterpretationTarget
    traceability_hash: StrictStr = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: StrictStr
    teacher_model: StrictStr = Field(..., min_length=1)
    teacher_prompt_version: StrictStr = Field(..., min_length=1)


class PredictionMetrics(BaseModel):
    """Метрики оценки ответа модели в predictions.jsonl (§6.3)."""

    model_config = ConfigDict(extra="forbid")

    hallucinated_numbers: int = Field(..., ge=0)
    traceability_ok: bool
    critical_coverage: float = Field(..., ge=0.0, le=1.0)
    recommendation_quality: float | None = Field(default=None, ge=0.0, le=1.0)


class PredictionsJsonlRecord(BaseModel):
    """Строка оценки качества модели predictions.jsonl (§6.3)."""

    model_config = ConfigDict(extra="forbid")

    example_id: StrictStr = Field(..., min_length=1)
    model_id: StrictStr = Field(..., min_length=1)
    prediction: InterpretationTarget
    metrics: PredictionMetrics
    rejected: bool = False
    latency_ms: float = Field(..., ge=0.0)
    tokens_in: int = Field(..., ge=0)
    tokens_out: int = Field(..., ge=0)

    @model_validator(mode="after")
    def _enforce_rejection_policy(self) -> "PredictionsJsonlRecord":
        if (self.metrics.hallucinated_numbers > 0 or not self.metrics.traceability_ok) and not self.rejected:
            raise ValueError(
                "При hallucinated_numbers > 0 или traceability_ok=False поле rejected обязано быть True (§6.3, §6.4)"
            )
        return self
