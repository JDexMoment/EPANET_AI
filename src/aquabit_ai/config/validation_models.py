"""Pydantic-схемы отчёта валидации validation_report.json (§4, Этап 1 и Этап 2)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aquabit_ai.config.manifest import ExecutionMode


class CheckCode(StrEnum):
    """Коды проверок Этапа 1 (Ingestion) и Этапа 2 (Validation)."""

    # Этап 1 — целостность архива и обязательных файлов
    INVALID_ZIP = "INVALID_ZIP"
    CORRUPTED_ZIP = "CORRUPTED_ZIP"
    ENCRYPTED_ZIP = "ENCRYPTED_ZIP"
    UNSAFE_ZIP_PATH = "UNSAFE_ZIP_PATH"
    MISSING_FILE = "MISSING_FILE"
    MANIFEST_INVALID = "MANIFEST_INVALID"

    # Этап 2 — табличная и ссылочная валидация
    ENCODING_ERROR = "ENCODING_ERROR"
    DELIMITER_MISMATCH = "DELIMITER_MISMATCH"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    UNIT_SUFFIX_MISSING = "UNIT_SUFFIX_MISSING"
    DUPLICATE_ID = "DUPLICATE_ID"
    DUPLICATE_CURVE_ID = "DUPLICATE_CURVE_ID"
    ORPHAN_REFERENCE = "ORPHAN_REFERENCE"
    SELF_LOOP_LINK = "SELF_LOOP_LINK"
    MISSING_ENTITY_NAMES = "MISSING_ENTITY_NAMES"
    ID_PREFIX_MISMATCH = "ID_PREFIX_MISMATCH"
    SCHEDULE_STEPS_NOT_24 = "SCHEDULE_STEPS_NOT_24"
    ABNORMAL_REQUIRED_PRESSURE = "ABNORMAL_REQUIRED_PRESSURE"
    PUMP_CURVE_INCOMPLETE = "PUMP_CURVE_INCOMPLETE"
    NO_RESULTS_BUT_MODE_RESULTS = "NO_RESULTS_BUT_MODE_RESULTS"
    RESULTS_IN_NO_RESULTS_MODE = "RESULTS_IN_NO_RESULTS_MODE"


CheckSeverity = Literal["warning", "error", "fatal"]
ValidationStatus = Literal["ok", "warning", "fatal"]


class ValidationCheckItem(BaseModel):
    """Результат сработавшей проверки валидации."""

    model_config = ConfigDict(extra="forbid")

    code: CheckCode
    severity: CheckSeverity
    count: int = Field(..., ge=1)
    message: str
    developer_hint: str | None = None
    examples: list[dict[str, Any]] = Field(default_factory=list)


class ValidationReport(BaseModel):
    """Итоговый отчёт валидации validation_report.json (§4, Этап 2)."""

    model_config = ConfigDict(extra="forbid")

    status: ValidationStatus
    requested_mode: ExecutionMode
    effective_mode: ExecutionMode
    mode_switched: bool = False
    strict_profile: bool = True
    blocked_pump_analysis_ids: list[str] = Field(default_factory=list)
    checks: list[ValidationCheckItem] = Field(default_factory=list)
