"""CLI-интерфейс модуля AquaBit AI (Этапы 0–3, пакетная проверка папок городов и профилировщик экспорта)."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Annotated, Optional

import typer

# Защита для Windows PowerShell (cp866 / cp1251): гарантируем UTF-8 при выводе кириллицы в консоль
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from aquabit_ai.config.manifest import ExecutionMode
from aquabit_ai.config.validation_models import CheckCode, ValidationCheckItem, ValidationReport
from aquabit_ai.ingest import (
    build_manifest_out,
    discover_city_directories,
    ingest_any_source,
    ingest_city_directory,
    inspect_aquabit_source,
    write_manifest_out,
)
from aquabit_ai.preprocess import PreprocessingFatalError, run_preprocessing
from aquabit_ai.profile import profile_aquabit_export, write_export_profile_artifacts
from aquabit_ai.report import render_fatal_diagnostic_html
from aquabit_ai.validate import run_validation
from aquabit_ai.zeros import audit_and_clean_zeros, write_zero_audit_reports

app = typer.Typer(
    name="epanet-ai",
    help="EPANET-AI / AquaBit-AI: валидация, очистка нулевых строк, профилирование экспорта и препроцессинг гидравлических расчётов",
    add_completion=False,
)


@app.command("ingest")
def cmd_ingest(
    source_path: Annotated[
        Path,
        typer.Argument(help="Путь к папке города (data/тенино), ZIP-экспорту или legacy CSV AquaBit"),
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Директория для артефактов")] = Path(
        "artifacts/out"
    ),
    run_id: Annotated[Optional[str], typer.Option("--run-id", help="Явный идентификатор запуска")] = None,
) -> None:
    """Этап 1 (Ingestion): чтение сырых строковых и широких таблиц и запись manifest_out.json."""
    bundle = ingest_any_source(source_path=source_path, run_id=run_id)
    manifest_out = build_manifest_out(bundle=bundle, stage_completed="stage1_ingest")
    out_file = write_manifest_out(manifest_out, out)
    typer.echo(
        json.dumps(
            {
                "run_id": bundle.run_id,
                "manifest_out": str(out_file),
                "tables_loaded": len(bundle.tables),
                "wide_matrices_loaded": sum(1 for t in bundle.tables.values() if t.wide_matrix is not None),
                "ingestion_issues": len(bundle.ingestion_issues),
                "has_fatal": bundle.has_fatal_ingestion_error,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if bundle.has_fatal_ingestion_error:
        raise typer.Exit(code=2)


@app.command("validate")
def cmd_validate(
    source_path: Annotated[
        Path,
        typer.Argument(help="Путь к папке города (data/тенино), ZIP-экспорту или legacy CSV AquaBit"),
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Директория для артефактов")] = Path(
        "artifacts/out"
    ),
    mode: Annotated[
        Optional[str],
        typer.Option("--mode", "-m", help="Режим пайплайна: results | no_results"),
    ] = None,
    legacy_compat: Annotated[
        bool,
        typer.Option(
            "--legacy-compat",
            help="Разрешить обратную совместимость (cp1251 / \\t / однофайловый анализ CSV)",
        ),
    ] = False,
    allow_broken_topology: Annotated[
        bool,
        typer.Option(
            "--allow-broken-topology",
            help="Понизить ошибки петель Начало==Конец (e702->c702,c702) до warning для продолжения анализа",
        ),
    ] = False,
    run_id: Annotated[Optional[str], typer.Option("--run-id", help="Явный идентификатор запуска")] = None,
) -> None:
    """Этап 1 + Этап 2 (Validation): проверка контракта, запись validation_report.json и fatal HTML."""
    parsed_mode: ExecutionMode | None = None
    if mode is not None:
        if mode not in {"results", "no_results"}:
            typer.echo(
                "Ошибка параметра --mode: допустимы только значения 'results' или 'no_results'.",
                err=True,
            )
            raise typer.Exit(code=1)
        parsed_mode = mode  # type: ignore[assignment]

    bundle = ingest_any_source(source_path=source_path, run_id=run_id)
    outcome = run_validation(
        bundle=bundle,
        requested_mode=parsed_mode,
        strict=not legacy_compat,
        allow_broken_topology=allow_broken_topology,
        output_dir=out,
    )

    summary = {
        "run_id": outcome.bundle.run_id,
        "status": outcome.report.status,
        "requested_mode": outcome.report.requested_mode,
        "effective_mode": outcome.report.effective_mode,
        "mode_switched": outcome.report.mode_switched,
        "checks_count": len(outcome.report.checks),
        "check_codes": [c.code.value for c in outcome.report.checks],
        "validation_report": str(outcome.validation_report_path),
        "manifest_out": str(outcome.manifest_out_path),
        "diagnostic_html": str(outcome.fatal_html_path) if outcome.fatal_html_path else None,
    }
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    if outcome.report.status == "fatal":
        raise typer.Exit(code=2)


@app.command("preprocess")
def cmd_preprocess(
    source_path: Annotated[
        Path,
        typer.Argument(help="Путь к папке города (data/тенино), ZIP-экспорту или legacy CSV AquaBit"),
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Директория для артефактов")] = Path(
        "artifacts/out"
    ),
    mode: Annotated[
        Optional[str],
        typer.Option("--mode", "-m", help="Режим пайплайна: results | no_results"),
    ] = None,
    legacy_compat: Annotated[
        bool,
        typer.Option(
            "--legacy-compat",
            help="Разрешить обратную совместимость (cp1251 / \\t / однофайловый анализ CSV)",
        ),
    ] = False,
    allow_broken_topology: Annotated[
        bool,
        typer.Option(
            "--allow-broken-topology",
            help="Разрешить нормализацию в Parquet даже при баге топологии Начало==Конец в выгрузке",
        ),
    ] = False,
    run_id: Annotated[Optional[str], typer.Option("--run-id", help="Явный идентификатор запуска")] = None,
) -> None:
    """Этапы 1 → 2 → 3 (Preprocessing): валидация + нормализация статики и широких матриц в Parquet."""
    parsed_mode: ExecutionMode | None = None
    if mode is not None:
        if mode not in {"results", "no_results"}:
            typer.echo(
                "Ошибка параметра --mode: допустимы только значения 'results' или 'no_results'.",
                err=True,
            )
            raise typer.Exit(code=1)
        parsed_mode = mode  # type: ignore[assignment]

    bundle = ingest_any_source(source_path=source_path, run_id=run_id)
    val_outcome = run_validation(
        bundle=bundle,
        requested_mode=parsed_mode,
        strict=not legacy_compat,
        allow_broken_topology=allow_broken_topology,
        output_dir=out,
    )
    if val_outcome.report.status == "fatal":
        typer.echo(
            json.dumps(
                {
                    "run_id": bundle.run_id,
                    "status": "fatal_at_validation",
                    "check_codes": [c.code.value for c in val_outcome.report.checks],
                    "validation_report": str(val_outcome.validation_report_path),
                    "diagnostic_html": str(val_outcome.fatal_html_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise typer.Exit(code=2)

    try:
        prep_outcome = run_preprocessing(
            bundle=bundle,
            output_dir=out,
            legacy_compat=legacy_compat,
            allow_broken_topology=allow_broken_topology,
        )
    except PreprocessingFatalError as exc:
        mapped_code = (
            CheckCode(exc.code)
            if exc.code in CheckCode._value2member_map_
            else CheckCode.SCHEMA_MISMATCH
        )
        fatal_report = ValidationReport(
            status="fatal",
            requested_mode=val_outcome.report.requested_mode,
            effective_mode=val_outcome.report.effective_mode,
            mode_switched=val_outcome.report.mode_switched,
            strict_profile=not legacy_compat,
            blocked_pump_analysis_ids=val_outcome.report.blocked_pump_analysis_ids,
            checks=[
                *val_outcome.report.checks,
                ValidationCheckItem(
                    code=mapped_code,
                    severity="fatal",
                    count=max(1, len(exc.examples)),
                    message=f"[{exc.code}] {exc.message}",
                    examples=exc.examples,
                ),
            ],
        )
        html_path = render_fatal_diagnostic_html(val_outcome.manifest_out, fatal_report, out)
        typer.echo(
            json.dumps(
                {
                    "run_id": bundle.run_id,
                    "status": "fatal_at_preprocessing",
                    "error_code": exc.code,
                    "diagnostic_html": str(html_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise typer.Exit(code=2)

    manifest_out = build_manifest_out(
        bundle=bundle,
        stage_completed="stage3_preprocess",
        requested_mode=val_outcome.report.requested_mode,
        effective_mode=val_outcome.report.effective_mode,
        mode_switched=val_outcome.report.mode_switched,
        validation_status=val_outcome.report.status,
    )
    write_manifest_out(manifest_out, out)

    typer.echo(
        json.dumps(
            {
                "run_id": bundle.run_id,
                "status": "ok",
                "effective_mode": val_outcome.report.effective_mode,
                "entities_registered": len(prep_outcome.entity_registry),
                "tables_normalized": len(prep_outcome.tables),
                "wide_matrices_normalized": len(prep_outcome.wide_artifacts),
                "quality_overall_status": prep_outcome.quality_report["overall"]["status"],
                "artifacts": {k: str(v) for k, v in prep_outcome.artifact_paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("batch-validate")
def cmd_batch_validate(
    data_root: Annotated[
        Path,
        typer.Argument(
            help="Путь к корневой папке городов (например, data/ с подпапками тенино, куляб, Алматы и др.)"
        ),
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Директория для отчётов по городам")] = Path(
        "artifacts/batch_validation"
    ),
    legacy_compat: Annotated[
        bool,
        typer.Option("--legacy-compat", help="Разрешить cp1251/не-UTF-8 без фатальной остановки"),
    ] = False,
) -> None:
    """Пакетная проверка всех папок городов внутри data/ с генерацией validation_report.json по каждому городу."""
    city_dirs = discover_city_directories(data_root)
    if not city_dirs:
        typer.echo(f"В каталоге '{data_root}' не найдено папок городов AquaBit.", err=True)
        raise typer.Exit(code=1)

    results = []
    for cdir in city_dirs:
        slug = re.sub(
            r"[^\w\-]+", "_", unicodedata.normalize("NFC", cdir.name), flags=re.UNICODE
        ).strip("_")
        city_out = out / slug
        bundle = ingest_city_directory(cdir)
        val_out = run_validation(bundle, strict=not legacy_compat, output_dir=city_out)
        results.append(
            {
                "city": cdir.name,
                "status": val_out.report.status,
                "tables_loaded": len(bundle.tables),
                "checks": [
                    {"code": c.code.value, "severity": c.severity, "count": c.count}
                    for c in val_out.report.checks
                ],
                "validation_report": str(val_out.validation_report_path),
                "diagnostic_html": str(val_out.fatal_html_path) if val_out.fatal_html_path else None,
            }
        )

    out.mkdir(parents=True, exist_ok=True)
    summary_file = out / "batch_summary.json"
    summary_payload = {
        "cities_checked": len(results),
        "ok_count": sum(1 for r in results if r["status"] == "ok"),
        "warning_count": sum(1 for r in results if r["status"] == "warning"),
        "fatal_count": sum(1 for r in results if r["status"] == "fatal"),
        "cities": results,
    }
    summary_file.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(json.dumps(summary_payload, ensure_ascii=False, indent=2))


@app.command("profile-export")
def cmd_profile_export(
    target_path: Annotated[
        Path,
        typer.Argument(
            help="Путь к папке города (data/тенино) ИЛИ ко всей папке data/ (тенино, хорезмская, Орша, модель семей, куляб, Алматы)"
        ),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Директория для JSON, Markdown и HTML отчётов оптимизации"),
    ] = Path("artifacts/export_profile"),
) -> None:
    """Анализирует информативность файлов, избыточность R0..R1439 и формирует ТЗ на оптимизацию экспорта."""
    profile = profile_aquabit_export(target_path)
    paths = write_export_profile_artifacts(profile, out)
    typer.echo(
        json.dumps(
            {
                "cities_analyzed": profile.cities_count,
                "total_mb": profile.total_mb,
                "wide_matrices_share_pct": profile.wide_bytes_share_pct,
                "redundant_bytes_pct": profile.redundant_bytes_pct,
                "savings_hourly_csv_pct": profile.savings_hourly_pct,
                "savings_compact_v2_pct": profile.savings_compact_v2_pct,
                "artifacts": {k: str(v) for k, v in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("check-zeros")
def cmd_check_zeros(
    target_path: Annotated[
        Path,
        typer.Argument(
            help="Путь к папке города (data/тенино) ИЛИ ко всей папке data/ для аудита нулевых значений"
        ),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Директория для JSON, Markdown и HTML отчётов аудита нулей"),
    ] = Path("artifacts/zero_audit"),
) -> None:
    """Проверяет все таблицы города (или всех городов в data/) на нулевые значения без перезаписи CSV."""
    report = audit_and_clean_zeros(target_path, perform_clean=False)
    paths = write_zero_audit_reports(report, out)
    typer.echo(
        json.dumps(
            {
                "mode": report.mode,
                "cities_checked": report.cities_count,
                "size_bytes": report.size_bytes_before,
                "cities": [
                    {
                        "city": c.city_name,
                        "transit_nodes_zero_pressure": c.pruned_transit_nodes_count,
                        "standby_pumps_all_zero": c.pruned_standby_pumps_count,
                        "zero_consumers": c.pruned_zero_consumers_count,
                        "zero_demand_matrix_rows": c.pruned_zero_demand_matrix_rows_count,
                        "floor_distribution": c.floor_distribution_by_required_pressure,
                        "schedule_non_24h_count": len(c.schedule_non_24h_ids),
                        "id_prefix_violations": c.id_prefix_violations_count,
                    }
                    for c in report.cities
                ],
                "artifacts": {k: str(v) for k, v in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("clean-zeros")
def cmd_clean_zeros(
    target_path: Annotated[
        Path,
        typer.Argument(
            help="Путь к папке города (data/тенино) ИЛИ ко всей папке data/ для очистки нулевых строк"
        ),
    ],
    out: Annotated[
        Optional[Path],
        typer.Option(
            "--out",
            "-o",
            help="Директория для очищенных CSV папок (по умолчанию <target>_cleaned; игнорируется при --in-place)",
        ),
    ] = None,
    report_dir: Annotated[
        Path,
        typer.Option(
            "--report-dir",
            help="Директория для JSON, Markdown и HTML отчётов об удалённых нулевых строках",
        ),
    ] = Path("artifacts/zero_clean_report"),
    in_place: Annotated[
        bool,
        typer.Option(
            "--in-place",
            help="Перезаписать исходные CSV на месте вместо копирования в отдельную папку",
        ),
    ] = False,
    prune_node_head: Annotated[
        bool,
        typer.Option(
            "--prune-node-head",
            help="Дополнительно удалить отфильтрованные транзитные узлы из Напор Узел.csv",
        ),
    ] = False,
) -> None:
    """Удаляет нулевые строки в Поток Насос, Потребители Узел, Потребление Узел и Узел (где не задано Hтреб)."""
    report = audit_and_clean_zeros(
        target_path,
        cleaned_output_root=out,
        perform_clean=True,
        in_place=in_place,
        prune_node_head=prune_node_head,
    )
    paths = write_zero_audit_reports(report, report_dir)
    typer.echo(
        json.dumps(
            {
                "mode": report.mode,
                "cities_cleaned": report.cities_count,
                "total_rows_removed": report.total_rows_removed,
                "size_bytes_before": report.size_bytes_before,
                "size_bytes_after": report.size_bytes_after,
                "bytes_saved": report.bytes_saved,
                "bytes_saved_pct": report.bytes_saved_pct,
                "cities": [
                    {
                        "city": c.city_name,
                        "cleaned_dir": c.cleaned_dir,
                        "rows_removed": c.total_rows_removed,
                        "bytes_saved_pct": c.bytes_saved_pct,
                        "pruned_transit_nodes": c.pruned_transit_nodes_count,
                        "pruned_standby_pumps": c.pruned_standby_pumps_count,
                        "pruned_zero_consumers": c.pruned_zero_consumers_count,
                        "pruned_zero_demand_matrix_rows": c.pruned_zero_demand_matrix_rows_count,
                    }
                    for c in report.cities
                ],
                "reports": {k: str(v) for k, v in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("inspect-headers")
def cmd_inspect_headers(
    target_path: Annotated[
        Path,
        typer.Argument(help="Путь к реальному ZIP, многосекционному CSV или папке города AquaBit"),
    ],
) -> None:
    """Инспектирует кодировки, разделители и маппинг реальных заголовков в field_aliases.yaml."""
    result = inspect_aquabit_source(target_path)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
