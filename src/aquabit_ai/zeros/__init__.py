"""Пакет проверки файлов на нулевые значения и очистки 4 целевых таблиц папок городов AquaBit (ADR-0008)."""

from __future__ import annotations

from aquabit_ai.zeros.cleaner import (
    CityZeroAuditResult,
    ColumnZeroStat,
    CorpusZeroAuditResult,
    TableZeroAuditResult,
    audit_and_clean_zeros,
    infer_floors_from_required_pressure,
)
from aquabit_ai.zeros.report_renderer import (
    render_zero_audit_html,
    render_zero_audit_markdown,
    write_zero_audit_reports,
)

__all__ = [
    "CityZeroAuditResult",
    "ColumnZeroStat",
    "CorpusZeroAuditResult",
    "TableZeroAuditResult",
    "audit_and_clean_zeros",
    "infer_floors_from_required_pressure",
    "render_zero_audit_html",
    "render_zero_audit_markdown",
    "write_zero_audit_reports",
]
