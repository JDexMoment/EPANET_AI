"""Оркестратор Этапа 2 — Validation: запуск всех проверок, запись validation_report.json и fatal HTML."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aquabit_ai.config.csv_contracts import AliasRegistry
from aquabit_ai.config.manifest import ExecutionMode, ManifestOutSchema
from aquabit_ai.config.validation_models import CheckCode, ValidationReport, ValidationStatus
from aquabit_ai.ingest.archive import IngestionBundle, build_manifest_out, write_manifest_out
from aquabit_ai.report.diagnostic import render_fatal_diagnostic_html
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


CONTAINER_FATAL_CODES = {
    CheckCode.INVALID_ZIP,
    CheckCode.CORRUPTED_ZIP,
    CheckCode.ENCRYPTED_ZIP,
    CheckCode.UNSAFE_ZIP_PATH,
}


@dataclass
class ValidationOutcome:
    """Полный результат прогона Этапа 1 + Этапа 2."""

    bundle: IngestionBundle
    report: ValidationReport
    manifest_out: ManifestOutSchema
    validation_report_path: Path | None = None
    manifest_out_path: Path | None = None
    fatal_html_path: Path | None = None


def infer_default_mode(bundle: IngestionBundle) -> ExecutionMode:
    """Определяет стартовый режим по manifest.calculation.status при отсутствии явного флага."""
    if bundle.manifest is not None and bundle.manifest.calculation.status == "performed":
        return "results"
    return "no_results"


def run_validation(
    bundle: IngestionBundle,
    requested_mode: ExecutionMode | None = None,
    strict: bool = True,
    allow_broken_topology: bool = False,
    aliases: AliasRegistry | None = None,
    output_dir: Path | None = None,
) -> ValidationOutcome:
    """Выполняет все проверки Этапа 2 над результатами IngestionBundle."""
    registry = aliases or AliasRegistry.from_yaml()
    initial_mode: ExecutionMode = requested_mode or infer_default_mode(bundle)

    checks = list(bundle.ingestion_issues)
    blocked_pump_ids: list[str] = []
    effective_mode: ExecutionMode = initial_mode
    mode_switched = False

    has_container_fatal = any(c.code in CONTAINER_FATAL_CODES for c in checks)

    if not has_container_fatal:
        for item in (
            check_encoding(bundle, strict=strict),
            check_delimiters(bundle, strict=strict),
            check_schemas(bundle, registry, strict=strict),
            check_unit_suffixes(bundle, registry),
            check_missing_entity_names(bundle, registry),
            check_id_prefixes(bundle, registry),
            check_duplicate_ids(bundle, registry, strict=strict),
            check_irregularity_curves(bundle, registry),
            check_schedule_24_steps(bundle, registry),
            check_required_pressure_norm(bundle, registry),
            check_self_loop_links(
                bundle,
                registry,
                strict=strict,
                allow_broken_topology=allow_broken_topology,
            ),
            check_orphan_references(
                bundle,
                registry,
                strict=strict,
                allow_broken_topology=allow_broken_topology,
            ),
        ):
            if item is not None:
                checks.append(item)

        pump_check, blocked_pump_ids = check_pump_curves_completeness(
            bundle, registry, strict=strict
        )
        if pump_check is not None:
            checks.append(pump_check)

        mode_check, effective_mode, mode_switched = check_mode_consistency(
            bundle, initial_mode, registry
        )
        if mode_check is not None:
            checks.append(mode_check)

    if any(c.severity == "fatal" for c in checks):
        overall_status: ValidationStatus = "fatal"
    elif checks:
        overall_status = "warning"
    else:
        overall_status = "ok"

    report = ValidationReport(
        status=overall_status,
        requested_mode=initial_mode,
        effective_mode=effective_mode,
        mode_switched=mode_switched,
        strict_profile=strict,
        blocked_pump_analysis_ids=blocked_pump_ids,
        checks=checks,
    )

    manifest_out = build_manifest_out(
        bundle=bundle,
        stage_completed="stage2_validate",
        requested_mode=initial_mode,
        effective_mode=effective_mode,
        mode_switched=mode_switched,
        validation_status=overall_status,
    )

    val_path: Path | None = None
    mout_path: Path | None = None
    fatal_html: Path | None = None

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        val_path = output_dir / "validation_report.json"
        val_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        mout_path = write_manifest_out(manifest_out, output_dir)
        if overall_status == "fatal":
            fatal_html = render_fatal_diagnostic_html(
                manifest_out=manifest_out,
                validation_report=report,
                output_dir=output_dir,
            )

    return ValidationOutcome(
        bundle=bundle,
        report=report,
        manifest_out=manifest_out,
        validation_report_path=val_path,
        manifest_out_path=mout_path,
        fatal_html_path=fatal_html,
    )
