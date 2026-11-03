"""Пакет валидации входных данных AquaBit (Этап 2 — Validation)."""

from __future__ import annotations

from aquabit_ai.validate.checks import (
    check_delimiters,
    check_duplicate_ids,
    check_encoding,
    check_id_prefixes,
    check_irregularity_curves,
    check_missing_entity_names,
    check_mode_consistency,
    check_orphan_references,
    check_pump_curves_completeness,
    check_required_pressure_norm,
    check_schedule_24_steps,
    check_schemas,
    check_self_loop_links,
    check_unit_suffixes,
)
from aquabit_ai.validate.engine import ValidationOutcome, infer_default_mode, run_validation

__all__ = [
    "ValidationOutcome",
    "check_delimiters",
    "check_duplicate_ids",
    "check_encoding",
    "check_id_prefixes",
    "check_irregularity_curves",
    "check_missing_entity_names",
    "check_mode_consistency",
    "check_orphan_references",
    "check_pump_curves_completeness",
    "check_required_pressure_norm",
    "check_schedule_24_steps",
    "check_schemas",
    "check_self_loop_links",
    "check_unit_suffixes",
    "infer_default_mode",
    "run_validation",
]
