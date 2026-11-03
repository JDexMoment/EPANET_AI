"""Этап 4 — Fact Extraction: извлечение тривиальных описательных агрегатов без пересчёта гидравлики."""

from __future__ import annotations

ALLOWED_AGGREGATIONS: tuple[str, ...] = (
    "raw",
    "min",
    "max",
    "mean",
    "sum",
    "count",
    "duration",
    "diff",
    "curve_interpolation",
)

__all__ = ["ALLOWED_AGGREGATIONS"]
