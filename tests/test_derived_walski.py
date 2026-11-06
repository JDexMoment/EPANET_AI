"""Тесты расчёта и сохранения производных гидравлических показателей по книге Walski et al. и ноутбука EPANET_AI_Pipeline.ipynb."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pandas as pd

from aquabit_ai.derived import compute_and_write_derived_city_tables
from tests.test_city_folder_and_profiler import build_city_13_csv_folder


def test_compute_and_write_derived_city_tables_exact_formulas(tmp_path: Path) -> None:
    """Проверяет точность формул скорости V=4Q/(pi*D^2), индекса Q/D, этажности, свободного напора и мощности насосов."""
    city_dir = build_city_13_csv_folder(
        tmp_path / "Алматы",
        broken_self_loop_topology=False,
        with_pump_switch_jump=True,
    )
    out_dir = tmp_path / "derived_out"
    res = compute_and_write_derived_city_tables(city_dir, out_dir, save_wide_matrices=True)

    assert res.nodes_analyzed == 6
    assert res.pipes_analyzed == 3
    assert res.pumps_analyzed == 2
    assert (out_dir / "Узел_этажность_и_свободный_напор.csv").exists()
    assert (out_dir / "Свободный напор Узел.csv").exists()
    assert (out_dir / "Труба_скорости_и_режимы_Walski.csv").exists()
    assert (out_dir / "Скорость Труба.csv").exists()
    assert (out_dir / "Насос_рабочие_точки_и_мощность.csv").exists()
    assert (out_dir / "График_потребления_анализ_24ч.csv").exists()
    assert (out_dir / "derived_formulas_manifest.json").exists()

    # 1. Проверяем этажность и свободный напор узлов: c171 -> 10 м = 1 этаж; c172 -> 14 м = 2 этажа
    nodes_df = pd.read_csv(out_dir / "Узел_этажность_и_свободный_напор.csv")
    c171 = nodes_df[nodes_df["ID"] == "c171"].iloc[0]
    c172 = nodes_df[nodes_df["ID"] == "c172"].iloc[0]
    assert int(c171["Этажность_дома"]) == 1
    assert int(c172["Этажность_дома"]) == 2
    # Для c171: Z = 122.20 м, HGL ~ 149.96..149.99 м -> H_своб ~ 27.76 м > 10 м (запас ~ +17.76 м)
    assert 27.5 <= float(c171["Свободный_напор_мин_м"]) <= 28.0
    assert float(c171["Запас_напора_мин_м"]) > 17.0

    # 2. Проверяем точную скорость в трубе e703 (D = 200 мм, Q = -45.0 * T109_HOURLY -> |Q_max| = 61.52 м3/ч):
    # A = pi * 0.2^2 / 4 = 0.0314159265 м2; V_max = (|Q_max| / 3600) / A = 0.5440 м/с
    pipes_df = pd.read_csv(out_dir / "Труба_скорости_и_режимы_Walski.csv")
    e703 = pipes_df[pipes_df["ID"] == "e703"].iloc[0]
    expected_area = math.pi * (0.2**2) / 4.0
    q_max_e703 = float(e703["Расход_макс_абс_м3_ч"])
    expected_v_max = (q_max_e703 / 3600.0) / expected_area
    assert abs(q_max_e703 - 61.52) < 0.05
    assert abs(float(e703["Площадь_сечения_м2"]) - expected_area) < 1e-5
    assert abs(float(e703["Скорость_макс_м_с"]) - expected_v_max) < 1e-3
    assert abs(float(e703["Упрощенный_индекс_Qмакс_делить_D"]) - (q_max_e703 / 200.0)) < 1e-3
    assert int(e703["Шагов_обратного_потока"]) == 1440
    assert "Турбулентный" in str(e703["Режим_течения_Re"])

    # Проверяем знак скорости в Скорость Труба.csv (для e703 на R0 расход Q0 = -40.46 м3/ч -> V0 = -0.3578 м/с < 0!)
    vel_wide = pd.read_csv(out_dir / "Скорость Труба.csv")
    v_e703_r0 = float(vel_wide[vel_wide["ID"] == "e703"]["R0"].iloc[0])
    expected_v_r0 = (-45.0 * 0.8991667 / 3600.0) / expected_area
    assert v_e703_r0 < 0.0
    assert abs(v_e703_r0 - expected_v_r0) < 1e-3

    # 3. Проверяем насосы: p1263 в резерве (0 кВт), p1264 циклический (>0 кВт и >0 кВт*ч/сут)
    pumps_df = pd.read_csv(out_dir / "Насос_рабочие_точки_и_мощность.csv")
    p1263 = pumps_df[pumps_df["ID"] == "p1263"].iloc[0]
    p1264 = pumps_df[pumps_df["ID"] == "p1264"].iloc[0]
    assert float(p1263["Моточасов_в_сутки"]) == 0.0
    assert float(p1264["Моточасов_в_сутки"]) > 16.0
    assert float(p1264["Гидравлическая_мощность_сред_кВт"]) > 0.0
    assert float(p1264["Гидравлическая_энергия_кВтч_сут"]) > 0.0


def test_standalone_ipynb_executes_all_cells_and_writes_derived_csvs(tmp_path: Path) -> None:
    """Гарантирует, что ноутбук EPANET_AI_Pipeline.ipynb исполняет все 10 клеток без консоли и сохраняет все файлы."""
    nb_file = Path("/home/user/EPANET_AI_Pipeline.ipynb")
    nb = json.loads(nb_file.read_text(encoding="utf-8"))

    ws = tmp_path / "epanet_ws"
    build_city_13_csv_folder(
        ws / "data" / "тенино",
        broken_self_loop_topology=False,
        with_pump_switch_jump=True,
    )

    prev_cwd = Path.cwd()
    try:
        os.chdir(ws)
        ns: dict = {}
        for idx, cell in enumerate([c for c in nb["cells"] if c["cell_type"] == "code"], start=1):
            exec(compile("".join(cell["source"]), f"<Cell {idx}>", "exec"), ns)
    finally:
        os.chdir(prev_cwd)

    derived_folder = ws / "data_cleaned" / "тенино" / "расчетные_параметры"
    assert (derived_folder / "Узел_этажность_и_свободный_напор.csv").exists()
    assert (derived_folder / "Свободный напор Узел.csv").exists()
    assert (derived_folder / "Труба_скорости_и_режимы_Walski.csv").exists()
    assert (derived_folder / "Скорость Труба.csv").exists()
    assert (derived_folder / "Насос_рабочие_точки_и_мощность.csv").exists()
    assert (derived_folder / "График_потребления_анализ_24ч.csv").exists()
    assert (derived_folder / "derived_formulas_manifest.json").exists()

    # Теперь запускаем второй ноутбук (EPANET_AI_Training.ipynb) поверх созданных data_cleaned и artifacts_epanet_ai!
    nb_train_file = Path("/home/user/EPANET_AI_Training.ipynb")
    nb_train = json.loads(nb_train_file.read_text(encoding="utf-8"))
    try:
        os.chdir(ws)
        ns_train: dict = {}
        for idx, cell in enumerate([c for c in nb_train["cells"] if c["cell_type"] == "code"], start=1):
            exec(compile("".join(cell["source"]), f"<Train Cell {idx}>", "exec"), ns_train)
    finally:
        os.chdir(prev_cwd)

    assert len(ns_train["ALL_CITY_FACTS"]) == 1
    assert len(ns_train["TEACHER_PROMPTS_POOL"]) >= 9
    assert ns_train["rejected_count"] == 0
    assert (ws / "training_epanet_ai" / "datasets" / "teacher_unlabeled_prompts.jsonl").exists()
    assert (ws / "training_epanet_ai" / "web_chat_batches" / "teacher_batch_тенино.md").exists()
    assert (ws / "training_epanet_ai" / "datasets" / "train.jsonl").exists()
    assert (ws / "training_epanet_ai" / "datasets" / "val.jsonl").exists()
    assert (ws / "training_epanet_ai" / "models" / "ranked_pipes_by_ai_risk.csv").exists()
    assert (ws / "training_epanet_ai" / "colab_training_bundle.zip").exists()
    assert ns_train["is_grounded"] is True


def test_teacher_distillation_critique_and_retry_loop_eliminates_hallucinations(
    tmp_path: Path,
) -> None:
    """Проверяет, что движок дистилляции ловит выдуманное число у Учителя с 1-й попытки, исправляет со 2-й и кэширует."""
    from aquabit_ai.jsonl import (
        DistillationTaskPrompt,
        distill_with_teacher_and_verify,
        generate_diverse_teacher_prompts,
    )

    sample_facts = {
        "city_name": "Орша",
        "zero_cleaning_summary": {"pruned_transit_nodes_count": 12, "pruned_standby_pumps_count": 3},
        "nodes_summary": {"consumer_nodes_count": 48, "deficit_nodes_count": 2, "worst_deficit_nodes": []},
        "pipes_summary": {"pipes_count": 55, "stagnant_pipes_under_0_3_m_s_count": 7, "top_stagnant_pipes": []},
        "pumps_summary": {"total_pumps_declared": 5, "active_pumps_count": 2, "total_hydraulic_energy_kwh_day": 412.5},
        "schedules_summary": {"schedules_count": 2, "all_24_hours_valid": True},
        "data_quality_flags": [],
    }
    prompts = generate_diverse_teacher_prompts(sample_facts)
    assert len(prompts) >= 8

    calls: list[int] = []

    def mock_teacher(dialog: list[dict[str, str]]) -> str:
        calls.append(1)
        # На первой попытке намеренно выдумываем число 77.77%, которого нет в JSON!
        if len(dialog) == 2:
            return (
                "<think>Посчитаю процент в уме...</think>"
                "В сети города Орша 48 узлов, при этом износ составляет 77.77% и дефицит на 2 узлах."
            )
        # После замечания верификатора возвращаем идеально чистый ответ строго по цифрам facts_inline!
        return (
            "В расчётной модели города «Орша» проанализировано 48 конечных узлов-потребителей и 55 участков труб "
            "(после фильтрации 12 транзитных узлов и 3 резервных насосов). Дефицит свободного напора зафиксирован на 2 узлах, "
            "а полезная гидравлическая энергия 2 работающих насосов составляет 412.5 кВт·ч/сут."
        )

    cache_file = tmp_path / "teacher_cache.jsonl"
    one_task = [prompts[0]]
    out1 = distill_with_teacher_and_verify(
        one_task,
        teacher_fn=mock_teacher,
        student_system_prompt="Система EPANET-AI",
        cache_jsonl_path=cache_file,
        max_retries_on_hallucination=2,
    )
    assert out1.accepted_first_try == 0
    assert out1.accepted_after_retry == 1
    assert out1.rejected_hallucinations == 0
    assert len(calls) == 2

    # Повторный запуск берёт ответ мгновенно из кэша без обращения к API Учителя!
    out2 = distill_with_teacher_and_verify(
        one_task,
        teacher_fn=mock_teacher,
        student_system_prompt="Система EPANET-AI",
        cache_jsonl_path=cache_file,
    )
    assert out2.loaded_from_cache == 1
    assert len(calls) == 2
