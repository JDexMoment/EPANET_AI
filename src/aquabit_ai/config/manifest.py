"""Pydantic-схемы входного manifest.json (§2) и выходного manifest_out.json (§3, Этап 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


ExecutionMode = Literal["results", "no_results"]
CalculationStatus = Literal["performed", "not_performed", "failed"]


def _validate_iso8601_with_tz(value: str, field_name: str) -> str:
    """Проверяет строгий формат ISO 8601 с явной таймзоной."""
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name}: пустая строка времени недопустима")
    candidate = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field_name}: некорректный ISO 8601 формат '{value}'") from exc
    if dt.tzinfo is None:
        raise ValueError(
            f"{field_name}: отсутствует явная таймзона в ISO 8601 строке '{value}' "
            "(TIMESTAMP_WITHOUT_TZ)"
        )
    return normalized


class ModelMetadata(BaseModel):
    """Описание гидравлической модели AquaBit."""

    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(..., min_length=1, description="Строковый ID модели")
    name: StrictStr = Field(..., min_length=1, description="Человекочитаемое имя модели")
    revision: StrictStr = Field(..., min_length=1, description="Ревизия модели")


class ScenarioMetadata(BaseModel):
    """Описание расчётного сценария AquaBit."""

    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(..., min_length=1, description="Строковый ID сценария")
    name: StrictStr = Field(..., min_length=1, description="Название сценария")
    revision: StrictStr = Field(..., min_length=1, description="Ревизия сценария")


class CalculationMetadata(BaseModel):
    """Параметры и статус гидравлического расчёта в ядре AquaBit."""

    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(..., min_length=1)
    status: CalculationStatus
    method_headloss: StrictStr | None = None
    solver: StrictStr | None = None
    tolerance: float | None = Field(default=None, gt=0)
    max_iterations: StrictInt | None = Field(default=None, ge=1)
    converged: bool | None = None
    convergence_iterations: StrictInt | None = Field(default=None, ge=0)


class PeriodMetadata(BaseModel):
    """Временной горизонт моделирования."""

    model_config = ConfigDict(extra="forbid")

    start: StrictStr
    end: StrictStr
    step_seconds: StrictInt = Field(..., gt=0)
    n_steps: StrictInt = Field(..., ge=1)
    timezone: StrictStr = Field(..., min_length=1)

    @field_validator("start")
    @classmethod
    def _check_start(cls, v: str) -> str:
        return _validate_iso8601_with_tz(v, "period.start")

    @field_validator("end")
    @classmethod
    def _check_end(cls, v: str) -> str:
        return _validate_iso8601_with_tz(v, "period.end")

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"period.timezone: неизвестная IANA таймзона '{v}'") from exc
        return v


class UnitsMetadata(BaseModel):
    """Канонические единицы измерения экспорта."""

    model_config = ConfigDict(extra="allow")

    head: StrictStr = Field(..., min_length=1)
    flow: StrictStr = Field(..., min_length=1)
    pressure: StrictStr = Field(..., min_length=1)
    velocity: StrictStr = Field(..., min_length=1)
    length: StrictStr = Field(..., min_length=1)
    diameter: StrictStr = Field(..., min_length=1)


class CountsMetadata(BaseModel):
    """Ожидаемые количества объектов сети по типам."""

    model_config = ConfigDict(extra="allow")

    nodes: StrictInt = Field(..., ge=0)
    pipes: StrictInt = Field(..., ge=0)
    pumps: StrictInt = Field(default=0, ge=0)
    reservoirs: StrictInt = Field(default=0, ge=0)
    valves: StrictInt = Field(default=0, ge=0)
    sources: StrictInt = Field(..., ge=0)


class ManifestSchema(BaseModel):
    """Корневая схема файла manifest.json из ZIP-экспорта AquaBit (§2)."""

    model_config = ConfigDict(extra="allow")

    schema_version: StrictStr = Field(..., min_length=1)
    export_id: StrictStr = Field(..., min_length=1)
    created_at: StrictStr
    aquabit_version: StrictStr = Field(..., min_length=1)
    model: ModelMetadata
    scenario: ScenarioMetadata
    calculation: CalculationMetadata
    period: PeriodMetadata
    units: UnitsMetadata
    counts: CountsMetadata
    missing_data_summary: dict[str, float | int] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def _check_created_at(cls, v: str) -> str:
        return _validate_iso8601_with_tz(v, "created_at")


class RawFileSnapshot(BaseModel):
    """Снимок отдельного файла из архива на Этапе 1 (без интерпретации содержимого)."""

    model_config = ConfigDict(extra="forbid")

    relative_path: str
    sha256: str
    size_bytes: int = Field(..., ge=0)
    is_csv: bool
    detected_encoding: str | None = None
    has_bom: bool = False
    detected_delimiter: str | None = None
    rows: int | None = None
    columns: int | None = None
    raw_headers: list[str] | None = None
    read_error: str | None = None


class ManifestOutSchema(BaseModel):
    """Выходной файл метаданных пайплайна manifest_out.json (§3, Этап 1.6)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    pipeline_version: str
    processed_at: str
    source_archive: str
    source_archive_sha256: str | None = None
    source_archive_size_bytes: int | None = None
    requested_mode: ExecutionMode | None = None
    effective_mode: ExecutionMode | None = None
    mode_switched: bool = False
    stage_completed: str
    validation_status: Literal["not_run", "ok", "warning", "fatal"] = "not_run"
    manifest: ManifestSchema | None = None
    raw_snapshot: list[RawFileSnapshot] = Field(default_factory=list)
