"""Юнит-тесты Этапа 0: Pydantic-схемы manifest.json, JSONL-потоков и реестра field_aliases.yaml."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from aquabit_ai.config import (
    AliasRegistry,
    FactQuality,
    FactSource,
    FactsJsonlRecord,
    InlineEntityFacts,
    InlineFactsBundle,
    InterpretationTarget,
    ManifestSchema,
    PredictionMetrics,
    PredictionsJsonlRecord,
    TracedFact,
    TrainingJsonlRecord,
    TrainingManifestSummary,
    TrainingPeriodSummary,
)
from tests.conftest import make_manifest_dict


def test_manifest_schema_valid() -> None:
    data = make_manifest_dict()
    parsed = ManifestSchema.model_validate(data)
    assert parsed.model.id == "M-Tenino"
    assert parsed.calculation.status == "performed"
    assert parsed.period.step_seconds == 3600


def test_manifest_rejects_numeric_id_and_missing_tz() -> None:
    bad_id = make_manifest_dict()
    bad_id["model"]["id"] = 12345  # запрещено §1.7 (ID обязаны быть строками)
    with pytest.raises(ValidationError):
        ManifestSchema.model_validate(bad_id)

    no_tz = make_manifest_dict()
    no_tz["period"]["start"] = "2026-10-30T00:00:00"  # без таймзоны
    with pytest.raises(ValidationError, match="TIMESTAMP_WITHOUT_TZ"):
        ManifestSchema.model_validate(no_tz)


def test_traced_fact_enforces_unit_and_null_rules() -> None:
    # Числовой факт без unit запрещён (§1.8)
    with pytest.raises(ValidationError, match="unit"):
        TracedFact(
            value=6.2,
            unit=None,
            source=FactSource(file="timeseries/node_pressure.csv", field="head_m", aggregation="min"),
        )

    # При is_null=True значение обязано быть None (§6.1)
    with pytest.raises(ValidationError, match="is_null=True"):
        TracedFact(
            value=0.0,
            unit="m",
            source=FactSource(file="nodes.csv", field="required_pressure_m"),
            quality=FactQuality(is_null=True),
        )

    # Валидный факт с числом 0.0 (ноль != null, §1.6)
    zero_fact = TracedFact(
        value=0.0,
        unit="m3_h",
        source=FactSource(file="demands.csv", field="base_demand_m3_h", aggregation="raw"),
        quality=FactQuality(is_null=False, is_zero=True),
    )
    assert zero_fact.value == 0.0
    assert zero_fact.quality is not None and zero_fact.quality.is_zero is True


def test_facts_jsonl_record_strict_string_id_and_snake_case() -> None:
    valid_fact = TracedFact(
        value=6.2,
        unit="m",
        source=FactSource(
            file="timeseries/node_pressure.csv",
            field="head_m",
            aggregation="min",
            n_steps=24,
        ),
        quality=FactQuality(is_null=False),
    )
    rec = FactsJsonlRecord(
        record_type="object",
        run_id="run-2026-10-30-001",
        object_type="node",
        object_id="00123",
        object_name="XY4973",
        mode="results",
        facts={"min_head": valid_fact},
    )
    assert rec.object_id == "00123"

    # Попытка передать числовой object_id отклоняется
    with pytest.raises(ValidationError):
        FactsJsonlRecord(
            record_type="object",
            run_id="run-2026-10-30-001",
            object_type="node",
            object_id=123,  # type: ignore[arg-type]
            mode="results",
            facts={"min_head": valid_fact},
        )

    # Не-snake_case ключ факта отклоняется (§6.1)
    with pytest.raises(ValidationError, match="snake_case"):
        FactsJsonlRecord(
            record_type="system",
            run_id="run-2026-10-30-001",
            mode="results",
            facts={"MinHead": valid_fact},
        )


def test_training_and_predictions_jsonl_schemas() -> None:
    min_head = TracedFact(
        value=6.2,
        unit="m",
        source=FactSource(file="timeseries/node_pressure.csv", field="head_m", aggregation="min"),
    )
    digest = "sha256:" + hashlib.sha256(b"test").hexdigest()
    train_rec = TrainingJsonlRecord(
        example_id="ex-000001",
        run_id="run-2026-10-30-001",
        mode="results",
        manifest=TrainingManifestSummary(
            model_id="M-Tenino",
            scenario_id="S-01",
            period=TrainingPeriodSummary(
                start="2026-10-30T00:00:00+05:00",
                end="2026-10-31T00:00:00+05:00",
                step_s=3600,
                n_steps=24,
            ),
            method="hazen_williams",
            converged=True,
        ),
        facts_ref="facts.jsonl#run-2026-10-30-001",
        facts_inline=InlineFactsBundle(
            nodes=[InlineEntityFacts(id="002", name="XY4973", facts={"min_head": min_head})]
        ),
        target=InterpretationTarget(
            summary="В узле XY4973 минимальный напор составил 6.2 м.",
            critical_issues=[],
            recommendations=[],
            limitations=[],
        ),
        traceability_hash=digest,
        created_at="2026-10-30T12:00:00Z",
        teacher_model="deepseek-v3",
        teacher_prompt_version="v1.0",
    )
    assert train_rec.mode == "results"

    # При hallucinated_numbers > 0 и rejected=False схема обязана отклонить запись (§6.3, §6.4)
    with pytest.raises(ValidationError, match="rejected"):
        PredictionsJsonlRecord(
            example_id="ex-000001",
            model_id="qwen3-4b-instruct-ft-v1",
            prediction=train_rec.target,
            metrics=PredictionMetrics(
                hallucinated_numbers=1,
                traceability_ok=False,
                critical_coverage=0.8,
            ),
            rejected=False,
            latency_ms=420.0,
            tokens_in=800,
            tokens_out=150,
        )


def test_alias_registry_resolves_canonical_and_russian_headers() -> None:
    reg = AliasRegistry.from_yaml()
    assert reg.resolve_header("head_m") == "head_m"
    assert reg.resolve_header("Напор в метрах") == "head_m"
    assert reg.resolve_header("Поток в кубических метрах") == "flow_m3_h"
    assert reg.resolve_header("Рассчитанный Напор в метрах") == "calculated_head_m"
    assert reg.has_canonical_unit_suffix("head_m") is True
    assert reg.has_canonical_unit_suffix("Напор в метрах") is False
