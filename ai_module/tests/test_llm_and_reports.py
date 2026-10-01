"""Tests for the LLM client (deterministic pilot) and the report generator."""

import json
from pathlib import Path

import pytest

from ai_module.config.settings import DATA_DIR, REPORTS_OUTPUT_DIR
from ai_module.context.context_builder import ContextBuilder
from ai_module.llm.qwen_client import LocalQwenClient
from ai_module.reports.report_generator import ReportGenerator
from ai_module.training.numeric_grounding import unverified_numbers

DISTRICT_INP = DATA_DIR / "raw_networks" / "city_district_si.inp"
UPGRADED_INP = DATA_DIR / "raw_networks" / "city_district_upgraded.inp"


@pytest.fixture(scope="module")
def payload():
    cb = ContextBuilder()
    p, _s, _a = cb.build_context(
        inp_file=str(DISTRICT_INP),
        mode="find_problems",
        selected_id="J-104",
        target_period=12,
    )
    return p


def test_prompts_contain_grounding_rules(payload):
    from ai_module.llm.prompts import build_messages_for_qwen

    sys_p, user_p = build_messages_for_qwen(payload, "find_problems", "")
    assert "НЕ ВЫДУМЫВАЙ" in sys_p
    assert "ЕДИНИЦ" in sys_p or "единицы" in sys_p
    assert "```json" in user_p
    assert payload.kpi.min_pressure_node in user_p


@pytest.mark.parametrize(
    "mode",
    ["what_happens", "explain_object", "find_problems", "why_happened", "generate_report", "ask_question"],
)
def test_gold_answers_are_grounded(payload, mode):
    client = LocalQwenClient(backend="deterministic_pilot")
    answer = client.synthesize_gold_engineering_answer(payload, mode, "Почему в узле низкий напор?")
    ctx = json.dumps(payload.model_dump(exclude_none=True), ensure_ascii=False)
    assert unverified_numbers(answer, ctx) == []
    assert len(answer) > 200
    # Mandatory engineering sections (Roadmap Section 10)
    assert "Наблюдение" in answer
    assert "Рекомендации" in answer
    assert "Ограничения" in answer


def test_all_modes_return_non_empty(payload):
    client = LocalQwenClient(backend="deterministic_pilot")
    for mode in ["what_happens", "explain_object", "find_problems", "why_happened", "generate_report"]:
        ans, backend_used, latency = client.generate(payload, mode, "")
        assert len(ans) > 200
        assert "deterministic" in backend_used
        assert latency >= 0


def test_report_generator_writes_files(payload):
    client = LocalQwenClient(backend="deterministic_pilot")
    answer = client.synthesize_gold_engineering_answer(payload, "generate_report", "")
    md_path, html_path = ReportGenerator.save_report(payload, answer)
    md_path, html_path = Path(md_path), Path(html_path)
    assert md_path.exists() and html_path.exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert "ДЕТЕРМИНИРОВАННЫЕ ФАКТЫ" in md_text
    assert "ИНЖЕНЕРНАЯ ИНТЕРПРЕТАЦИЯ" in md_text
    assert payload.kpi.min_pressure_node in md_text


def test_compare_scenarios_mode():
    cb = ContextBuilder()
    p, _s, _a = cb.build_context(
        inp_file=str(DISTRICT_INP),
        mode="compare_scenarios",
        compare_inp_file=str(UPGRADED_INP),
        target_period=12,
    )
    client = LocalQwenClient(backend="deterministic_pilot")
    answer = client.synthesize_gold_engineering_answer(p, "compare_scenarios", "")
    assert "Сравнение сценариев" in answer
    assert "ΔP" in answer or "Δ" in answer
