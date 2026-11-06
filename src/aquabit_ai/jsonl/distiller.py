"""Движок дистилляции знаний (Teacher -> Student Knowledge Distillation) с анти-галлюцинационной самокоррекцией.

Реализует закрытый контур разметки данных сильной моделью-Учителем:
1. Генерирует разнообразный пул инженерных промптов по каждому городу на основе строгого `facts.json`
   (сырые CSV объёмом в десятки МБ в API Учителя НЕ передаются).
2. Отправляет запрос в любой OpenAI-совместимый API Учителя (OpenRouter, DeepSeek, OpenAI, Cloud.ru GigaChat,
   локальный Ollama / LM Studio / vLLM) с пошаговым кэшированием в `teacher_cache.jsonl`.
3. Проверяет каждый ответ Учителя детектором чисел `verify_no_hallucinated_numbers`:
   если Учитель допустил устный пересчёт или выдумал цифру, автоматически отправляет корректирующий
   запрос (Critique & Retry) с точным списком неподтверждённых чисел.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Callable

import httpx


ALLOWED_NORMATIVE_CONSTANTS: frozenset[float] = frozenset(
    {0.0, 0.3, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 9.0, 10.0, 14.0, 18.0, 22.0, 24.0, 26.0, 60.0, 1440.0, 2000.0, 4000.0}
)

TEACHER_SYSTEM_PROMPT = (
    "Ты — главный инженер-гидравлик систем водоснабжения (авторского уровня руководства Walski et al. "
    "'Advanced Water Distribution Modeling and Management' и СП 31.13330.2021). "
    "Твоя задача — написать эталонный, глубокий, профессиональный инженерный ответ для обучения младшей ИИ-модели EPANET-AI.\n\n"
    "ЖЕЛЕЗНЫЕ ПРАВИЛА РАЗМЕТКИ (нарушение бракует пример):\n"
    "1. Опирайся ИСКЛЮЧИТЕЛЬНО на переданный JSON-блок `facts_inline`.\n"
    "2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выполнять устный счёт в уме (не складывай, не дели, не вычисляй проценты, если их нет в JSON) "
    "и запрещено приводить любые числовые значения, отсутствующие во входном `facts_inline` "
    "(кроме справочных констант нормативов: 10 м и +4 м на этаж по СП 31.13330.2021, 60 м макс. напор, 0.3 / 1.5 / 3.0 м/с скорости по Walski, 24 ч, 1440 шагов).\n"
    "3. Всегда называй конкретные строковые ID узлов (c*), труб (e*), насосов (p*), кривых (u*, t*) из JSON и объясняй физическую причинно-следственную связь.\n"
    "4. Если инженер спрашивает параметр, которого нет в `facts_inline` (например, электрический КПД насоса, тариф в рублях, остаточный хлор, износ труб в годах), "
    "строго укажи, каких именно исходных данных не хватает, и НЕ выдумывай оценочных цифр."
)


def strip_thinking_blocks(text: str) -> str:
    """Удаляет внутренние блоки размышлений <think>...</think> у reasoning-моделей Учителя."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()


def extract_json_numbers(obj: Any, acc: set[float] | None = None) -> set[float]:
    """Рекурсивно извлекает все числа из JSON-структуры фактов."""
    if acc is None:
        acc = set()
    if isinstance(obj, bool) or obj is None:
        return acc
    if isinstance(obj, (int, float)):
        if not math.isnan(float(obj)):
            acc.add(round(float(obj), 6))
        return acc
    if isinstance(obj, str):
        for m in re.findall(r"-?\d+(?:\.\d+)?", obj):
            acc.add(round(float(m), 6))
        return acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            extract_json_numbers(k, acc)
            extract_json_numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            extract_json_numbers(item, acc)
    return acc


def verify_response_numbers(text: str, facts_inline: dict[str, Any]) -> tuple[bool, list[str]]:
    """Возвращает (True, []), если все числа в ответе подтверждены входным facts_inline."""
    allowed = extract_json_numbers(facts_inline) | set(ALLOWED_NORMATIVE_CONSTANTS)
    # Исключаем буквенно-цифровые ID (c171, e702, p1264, v1284, u123, t109, R1439) и нумерацию списков "1.", "2."
    cleaned = re.sub(r"\b[cepvutR]\d+\b", " ", text)
    cleaned = re.sub(r"(?m)^\s*\d+[\.\)]\s+", " ", cleaned)
    bad: list[str] = []
    for tok in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", cleaned):
        val = round(float(tok), 6)
        if not any(abs(val - ref) <= 1e-3 for ref in allowed):
            bad.append(tok)
    return (len(bad) == 0, bad)


@dataclass
class DistillationTaskPrompt:
    """Одна неразмеченная задача для Модели-Учителя."""

    prompt_id: str
    city: str
    task_type: str
    question: str
    facts_inline: dict[str, Any]

    def build_user_message(self) -> str:
        return (
            f"Вопрос инженера: {self.question}\n\n"
            f"Факты расчёта (facts_inline):\n```json\n{json.dumps(self.facts_inline, ensure_ascii=False, indent=2)}\n```"
        )


@dataclass
class DistillationOutcome:
    """Сводный отчёт о разметке датасета Моделью-Учителем."""

    total_prompts: int = 0
    accepted_first_try: int = 0
    accepted_after_retry: int = 0
    loaded_from_cache: int = 0
    rejected_hallucinations: int = 0
    accepted_records: list[dict[str, Any]] = dc_field(default_factory=list)
    rejected_details: list[dict[str, Any]] = dc_field(default_factory=list)


def generate_diverse_teacher_prompts(facts: dict[str, Any]) -> list[DistillationTaskPrompt]:
    """Формирует богатый набор разнообразных вопросов для разметки Моделью-Учителем по одному городу."""
    cname = facts["city_name"]
    ns = facts.get("nodes_summary", {})
    ps = facts.get("pipes_summary", {})
    pms = facts.get("pumps_summary", {})
    zs = facts.get("zero_cleaning_summary", {})
    qflags = facts.get("data_quality_flags", [])

    compact_overview = {
        "city_name": cname,
        "zero_cleaning_summary": zs,
        "nodes_overview": {k: v for k, v in ns.items() if not isinstance(v, list)},
        "pipes_overview": {k: v for k, v in ps.items() if not isinstance(v, list)},
        "pumps_overview": {k: v for k, v in pms.items() if not isinstance(v, list)},
        "data_quality_flags": qflags,
    }

    raw_specs: list[tuple[str, str, dict[str, Any]]] = [
        (
            "executive_summary",
            f"Подготовь развёрнутую аналитическую записку для главного инженера водоканала по результатам гидравлического расчёта сети «{cname}»: оцени общий баланс, узкие места и первоочередные шаги.",
            compact_overview,
        ),
        (
            "pressure_and_storeys",
            f"Проведи детальный разбор режима свободных напоров в городе «{cname}» с учётом этажности жилой застройки по СП 31.13330.2021. Где есть дефицит или опасный избыток давления свыше 60 м?",
            {"city_name": cname, "nodes_summary": ns},
        ),
        (
            "new_building_connection",
            f"Застройщик планирует подключение новой застройки в сети «{cname}». Судя по текущему распределению свободных напоров и проблемным узлам, какие риски по давлению есть в существующей сети и на что обратить внимание при выдаче техусловий?",
            {"city_name": cname, "nodes_summary": ns},
        ),
        (
            "pipe_hydraulics_and_transients",
            f"Оцени скоростной режим трубопроводов города «{cname}» с позиции руководства Walski: выдели участки с повышенными потерями, риском гидравлического удара (>3.0 м/с) и реверсами направления потока.",
            {"city_name": cname, "pipes_summary": ps},
        ),
        (
            "water_quality_stagnation",
            f"В каких трубах сети «{cname}» наблюдается риск застоя воды (<0.3 м/с) и наибольшее время пробега воды? Какие эксплуатационные мероприятия (кольцевание, промывка, переключение задвижек) целесообразны?",
            {"city_name": cname, "pipes_summary": ps},
        ),
        (
            "pump_scheduling_and_vfd",
            f"Проанализируй работу насосных агрегатов модели «{cname}»: соотношение рабочих и резервных насосов, цикличность пусков, напор TDH и полезную гидравлическую энергию. Нужна ли корректировка графика или частотное регулирование (ЧРП)?",
            {"city_name": cname, "pumps_summary": pms, "excess_nodes_count": ns.get("excess_pressure_over_60m_nodes_count", 0)},
        ),
        (
            "dispatcher_night_regime",
            f"Диспетчер спрашивает, как ведёт себя сеть «{cname}» в течение суток: есть ли переключения направлений потока в трубах, избыточные напоры и циклические включения насосов?",
            {
                "city_name": cname,
                "excess_pressure_over_60m_nodes_count": ns.get("excess_pressure_over_60m_nodes_count", 0),
                "highest_excess_pressure_nodes": ns.get("highest_excess_pressure_nodes", []),
                "top_reverse_flow_pipes": ps.get("top_reverse_flow_pipes", []),
                "pumps_summary": pms,
            },
        ),
        (
            "model_data_audit",
            f"Оцени корректность самой расчётной схемы «{cname}» после очистки нулевых строк: сколько транзитных узлов и резервных насосов было отфильтровано и есть ли ошибки топологии или графиков?",
            {
                "city_name": cname,
                "zero_cleaning_summary": zs,
                "schedules_summary": facts.get("schedules_summary", {}),
                "self_loop_topology_pipes_count": ps.get("self_loop_topology_pipes_count", 0),
                "data_quality_flags": qflags,
            },
        ),
        (
            "refusal_missing_chlorine_and_cost",
            f"Посчитай для города «{cname}» годовые затраты на электроэнергию насосных станций в рублях, средний КПД электродвигателей и концентрацию остаточного хлора у самых удалённых потребителей.",
            {
                "city_name": cname,
                "pumps_summary": {
                    "active_pumps_count": pms.get("active_pumps_count", 0),
                    "total_hydraulic_energy_kwh_day": pms.get("total_hydraulic_energy_kwh_day", 0.0),
                },
            },
        ),
    ]

    # Добавляем прицельные вопросы по реальным критическим узлам и трубам города
    for d_node in ns.get("worst_deficit_nodes", [])[:3]:
        raw_specs.append(
            (
                "node_root_cause",
                f"Разбери подробно проблемный узел {d_node['node_id']} в городе «{cname}»: почему возникает нехватка напора и как её устранить?",
                {"city_name": cname, "node_diagnostic": d_node},
            )
        )
    for s_pipe in ps.get("top_stagnant_pipes", [])[:3]:
        raw_specs.append(
            (
                "pipe_stagnation_card",
                f"Дай инженерную оценку режима работы участка трубопровода {s_pipe['pipe_id']} в модели «{cname}» и предложи меры по улучшению водообмена.",
                {"city_name": cname, "pipe_diagnostic": s_pipe},
            )
        )

    prompts: list[DistillationTaskPrompt] = []
    for task_type, q_txt, payload in raw_specs:
        digest = hashlib.sha1(f"{cname}::{task_type}::{q_txt}".encode("utf-8")).hexdigest()[:12]
        prompts.append(
            DistillationTaskPrompt(
                prompt_id=f"{cname}_{task_type}_{digest}",
                city=cname,
                task_type=task_type,
                question=q_txt,
                facts_inline=payload,
            )
        )
    return prompts


def call_openai_compatible_teacher(
    messages: list[dict[str, str]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    timeout_s: float = 90.0,
) -> str:
    """Универсальный вызов Модели-Учителя по OpenAI-совместимому протоколу (OpenRouter, DeepSeek, OpenAI, Ollama, vLLM)."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    raw_content = data["choices"][0]["message"]["content"] or ""
    return strip_thinking_blocks(raw_content)


def distill_with_teacher_and_verify(
    tasks: list[DistillationTaskPrompt],
    *,
    teacher_fn: Callable[[list[dict[str, str]]], str],
    student_system_prompt: str,
    cache_jsonl_path: Path | None = None,
    max_retries_on_hallucination: int = 2,
) -> DistillationOutcome:
    """Размечает пул задач сильной моделью-Учителем с кэшированием и автокоррекцией неподтверждённых цифр."""
    outcome = DistillationOutcome(total_prompts=len(tasks))
    cached_by_id: dict[str, dict[str, Any]] = {}

    if cache_jsonl_path is not None and cache_jsonl_path.exists():
        for line in cache_jsonl_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if "prompt_id" in rec:
                    cached_by_id[rec["prompt_id"]] = rec

    if cache_jsonl_path is not None:
        cache_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    for task in tasks:
        if task.prompt_id in cached_by_id:
            outcome.loaded_from_cache += 1
            outcome.accepted_records.append(cached_by_id[task.prompt_id])
            continue

        user_msg = task.build_user_message()
        dialog: list[dict[str, str]] = [
            {"role": "system", "content": TEACHER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        accepted_answer: str | None = None
        last_bad_nums: list[str] = []
        used_retry = False

        for attempt in range(max_retries_on_hallucination + 1):
            candidate = strip_thinking_blocks(teacher_fn(dialog))
            is_ok, bad_nums = verify_response_numbers(candidate, task.facts_inline)
            if is_ok and len(candidate) >= 40:
                accepted_answer = candidate
                used_retry = attempt > 0
                break

            last_bad_nums = bad_nums
            dialog.append({"role": "assistant", "content": candidate})
            dialog.append(
                {
                    "role": "user",
                    "content": (
                        f"ОШИБКА ПРОВЕРКИ ЧИСЕЛ: в твоём ответе обнаружены числа {bad_nums}, которых НЕТ во входном `facts_inline`. "
                        "Устный пересчёт процентов/разностей/сумм запрещён! Перепиши ответ заново целиком, используя "
                        "ТОЛЬКО точные числа из переданного JSON `facts_inline`."
                    ),
                }
            )

        if accepted_answer is not None:
            if used_retry:
                outcome.accepted_after_retry += 1
            else:
                outcome.accepted_first_try += 1

            sft_record = {
                "prompt_id": task.prompt_id,
                "city": task.city,
                "task_type": task.task_type,
                "source": "teacher_distilled",
                "facts_inline": task.facts_inline,
                "messages": [
                    {"role": "system", "content": student_system_prompt},
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": accepted_answer},
                ],
            }
            outcome.accepted_records.append(sft_record)
            if cache_jsonl_path is not None:
                with cache_jsonl_path.open("a", encoding="utf-8") as cf:
                    cf.write(json.dumps(sft_record, ensure_ascii=False) + "\n")
        else:
            outcome.rejected_hallucinations += 1
            outcome.rejected_details.append(
                {
                    "prompt_id": task.prompt_id,
                    "city": task.city,
                    "task_type": task.task_type,
                    "unverified_numbers": last_bad_nums,
                }
            )

    return outcome
