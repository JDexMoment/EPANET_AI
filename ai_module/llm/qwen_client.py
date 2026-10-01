import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

from ai_module.config.settings import (
    LLM_BACKEND,
    LLM_MODEL_NAME,
    LOCAL_LLM_API_URL,
    LORA_ADAPTER_PATH,
    OLLAMA_MODEL_NAME,
)
from ai_module.context.schemas import LLMContextPayload
from ai_module.llm.prompts import build_messages_for_qwen


class LocalQwenClient:
    """
    Swappable Local LLM Interface for Qwen3 4B / 8B (Roadmap Section 6, 13, 15).
    Supports:
      1. Local OpenAI-compatible server (Ollama / vLLM / llama.cpp)
      2. Local HuggingFace Transformers + PEFT LoRA weights (`hf_local`)
      3. Deterministic Gold-Standard Engineering Synthesizer (`deterministic_pilot`)
         used both as a zero-hallucination fallback when no GPU server is active
         and as the teacher synthesizer for generating SFT training datasets.
    """

    def __init__(self, backend: str = LLM_BACKEND):
        self.backend = backend
        self._hf_pipeline = None

    def generate(
        self,
        context: LLMContextPayload,
        mode: str,
        user_question: str = "",
    ) -> Tuple[str, str, float]:
        t0 = time.perf_counter()
        sys_prompt, user_prompt = build_messages_for_qwen(context, mode, user_question)

        # 1. Try local OpenAI-compatible server (Ollama / vLLM / llama.cpp) if configured or auto
        if self.backend in ("auto", "ollama", "openai_compat"):
            ok, text, used_name = self._try_local_http_llm(sys_prompt, user_prompt)
            if ok:
                elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
                return text, used_name, elapsed

        # 2. Try local HuggingFace Transformers + LoRA if explicitly requested
        if self.backend == "hf_local":
            ok, text, used_name = self._try_hf_local(sys_prompt, user_prompt)
            if ok:
                elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
                return text, used_name, elapsed

        # 3. Deterministic Gold-Standard Engineering Synthesizer (zero hallucinations)
        text = self.synthesize_gold_engineering_answer(context, mode, user_question)
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        return text, "deterministic_analytics_synthesizer (Qwen3-ready)", elapsed

    def _try_local_http_llm(self, sys_prompt: str, user_prompt: str) -> Tuple[bool, str, str]:
        url = f"{LOCAL_LLM_API_URL.rstrip('/')}/chat/completions"
        payload = {
            "model": OLLAMA_MODEL_NAME,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 1200,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    content = data["choices"][0]["message"]["content"]
                    return True, content, f"local_http:{OLLAMA_MODEL_NAME}"
        except Exception:
            pass
        return False, "", ""

    def _try_hf_local(self, sys_prompt: str, user_prompt: str) -> Tuple[bool, str, str]:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            if self._hf_pipeline is None:
                tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_NAME, trust_remote_code=True)
                model = AutoModelForCausalLM.from_pretrained(
                    LLM_MODEL_NAME,
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                    device_map="auto",
                    trust_remote_code=True,
                )
                from pathlib import Path
                if Path(LORA_ADAPTER_PATH).exists():
                    from peft import PeftModel
                    model = PeftModel.from_pretrained(model, LORA_ADAPTER_PATH)
                self._hf_pipeline = (tokenizer, model)

            tokenizer, model = self._hf_pipeline
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ]
            text_input = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
            inputs = tokenizer([text_input], return_tensors="pt").to(model.device)
            with torch.no_grad():
                generated_ids = model.generate(**inputs, max_new_tokens=1024, temperature=0.1, do_sample=False)
            output_ids = generated_ids[0][len(inputs.input_ids[0]):]
            ans = tokenizer.decode(output_ids, skip_special_tokens=True)
            return True, ans, f"hf_local:{LLM_MODEL_NAME}"
        except Exception:
            return False, "", ""

    @staticmethod
    def synthesize_gold_engineering_answer(
        ctx: LLMContextPayload,
        mode: str,
        user_question: str = "",
    ) -> str:
        """
        Generates a strictly grounded, structured Russian engineering response directly from
        `LLMContextPayload`. Every single number is cited with `[объект: параметр = значение]`.
        Follows Roadmap Section 10 prompt rules and Section 2 mode definitions.
        """
        kpi = ctx.kpi
        net = ctx.network_summary
        an = ctx.analysis
        sel = ctx.selection
        det = ctx.selected_object_details or {}
        nb = ctx.topological_neighborhood or {}
        vp = ctx.viewport_context or {}
        alerts = ctx.alerts

        lines: List[str] = []

        if mode == "compare_scenarios" and ctx.scenario_comparison:
            sc = ctx.scenario_comparison
            kd = sc["kpi_deltas"]
            lines.append(f"### Сравнение сценариев: «{sc['baseline_scenario']}» vs «{sc['compared_scenario']}»")
            lines.append("")
            lines.append("#### 1. Наблюдение (Факты расчёта)")
            lines.append(
                f"- **Минимальный напор в сети**: изменился с `{kd['min_pressure_m_before']} м` до "
                f"`{kd['min_pressure_m_after']} м` (разница ΔP = `{kd['min_pressure_delta_m']:+.2f} м`)."
            )
            lines.append(
                f"- **Максимальная скорость потока**: изменилась с `{kd['max_velocity_mps_before']} м/с` до "
                f"`{kd['max_velocity_mps_after']} м/с` (разница ΔV = `{kd['max_velocity_delta_mps']:+.2f} м/с`)."
            )
            lines.append(
                f"- **Общее число инженерных аномалий**: было `{kd['alerts_count_before']}`, стало `{kd['alerts_count_after']}` "
                f"(изменение: `{kd['alerts_count_delta']:+d}`)."
            )
            if sc.get("modified_parameters"):
                lines.append("- **Зафиксированные конструктивные/режимные изменения в модели**:")
                for mp in sc["modified_parameters"][:8]:
                    lines.append(
                        f"  - [Объект {mp['object']}: {mp['parameter']} изменён с {mp['before']} на {mp['after']}]"
                    )
            if sc.get("top_node_pressure_changes"):
                lines.append("- **Узлы с наибольшим изменением свободного напора**:")
                for nd in sc["top_node_pressure_changes"][:5]:
                    lines.append(
                        f"  - [Узел {nd['node_id']}: pressure_m было {nd['pressure_before_m']} м → стало {nd['pressure_after_m']} м, Δ = {nd['delta_pressure_m']:+.2f} м]"
                    )
            lines.append("")
            lines.append("#### 2. Вероятная инженерная причина")
            lines.append(
                "- Изменение гидравлического сопротивления участков (диаметров, шероховатости или статуса задвижек) "
                "привело к перераспределению потоков и изменению потерь напора по магистральным направлениям."
            )
            lines.append("")
            lines.append("#### 3. Рекомендации")
            lines.append(
                "- Если во втором сценарии остались узлы с напором ниже нормативного (`15.0 м`), рекомендуется проверить "
                "лимитирующие трубы с максимальным уклоном (`headloss_m_per_km`)."
            )
            lines.append("")
            lines.append("#### 4. Ограничения и доказательная база (Evidence)")
            lines.append(
                f"- Сопоставление выполнено для шага времени `t = {an.active_time_h} ч` (статус решателя: `{an.status}`)."
            )
            return "\n".join(lines)

        if mode == "explain_object" and det:
            obj_id = det.get("id", sel.id)
            obj_type = det.get("type", sel.type)
            cur = det.get("current_state", {})
            ts = det.get("time_series_summary", {})
            lines.append(f"### Инженерный разбор объекта: `{obj_id}` (тип: `{obj_type}`)")
            lines.append("")
            lines.append("#### 1. Наблюдение (Факты расчёта)")
            if det.get("object_class") == "node":
                lines.append(
                    f"- **Конструктивные параметры**: геодезическая отметка [Узел {obj_id}: elevation_m = {det.get('elevation_m')} м], "
                    f"базовый водоразбор [Узел {obj_id}: base_demand_lps = {det.get('base_demand_lps')} л/с]."
                )
                lines.append(
                    f"- **Текущее состояние (шаг t = {an.active_time_h} ч)**: свободный напор [Узел {obj_id}: pressure_m = {cur.get('pressure_m')} м], "
                    f"пьезометрический напор [Узел {obj_id}: head_m = {cur.get('head_m')} м], фактический отбор [Узел {obj_id}: demand_lps = {cur.get('demand_lps')} л/с]."
                )
                lines.append(
                    f"- **Суточный диапазон за {an.duration_h} ч**: минимальное давление `{ts.get('min_pressure_m')} м`, "
                    f"максимальное давление `{ts.get('max_pressure_m')} м`, пиковый расход `{ts.get('max_demand_lps')} л/с`."
                )
            else:
                lines.append(
                    f"- **Конструктивные параметры**: участок соединяет узлы `{det.get('from_node')}` → `{det.get('to_node')}`, "
                    f"диаметр [Участок {obj_id}: diameter_mm = {det.get('diameter_mm')} мм], длина [Участок {obj_id}: length_m = {det.get('length_m')} м], "
                    f"шероховатость [Участок {obj_id}: roughness = {det.get('roughness')}]."
                )
                lines.append(
                    f"- **Текущее состояние (шаг t = {an.active_time_h} ч)**: статус `{cur.get('status')}`, расход [Участок {obj_id}: flow_lps = {cur.get('flow_lps')} л/с], "
                    f"скорость [Участок {obj_id}: velocity_mps = {cur.get('velocity_mps')} м/с], гидравлический уклон [Участок {obj_id}: headloss_m_per_km = {cur.get('headloss_m_per_km')} м/км]."
                )
                lines.append(
                    f"- **Суточный диапазон за {an.duration_h} ч**: максимальная скорость `{ts.get('max_velocity_mps')} м/с`, "
                    f"максимальный расход `{ts.get('max_abs_flow_lps')} л/с`, часов с обратным направлением потока: `{ts.get('reverse_flow_periods')}`."
                )

            lines.append("")
            lines.append("#### 2. Роль в системе и гидравлическое окружение")
            conn = nb.get("connected_links", [])
            if conn:
                lines.append(f"- К объекту `{obj_id}` примыкает `{len(conn)}` активных гидравлических связей:")
                for c in conn[:6]:
                    lines.append(
                        f"  - [Связь {c['link_id']} ({c['type']}): поток {c['actual_flow_from']} → {c['actual_flow_to']}, "
                        f"D = {c['diameter_mm']} мм, Q = {c['flow_lps']} л/с, V = {c['velocity_mps']} м/с, "
                        f"уклон i = {c['headloss_m_per_km']} м/км, полные потери ΔH = {c['total_headloss_m']} м]"
                    )
            lines.append("")
            lines.append("#### 3. Рекомендации")
            obj_alerts = [a for a in alerts if a.object == obj_id]
            if obj_alerts:
                for oa in obj_alerts:
                    lines.append(f"- Зафиксирована аномалия `{oa.type}` ({oa.severity}): {oa.description}.")
                for rule in ctx.applicable_rules[:2]:
                    for rec in rule.get("recommendations", [])[:2]:
                        lines.append(f"- {rec}.")
            else:
                lines.append(f"- На шаге `t = {an.active_time_h} ч` параметры объекта `{obj_id}` находятся в пределах допустимых рабочих значений.")

            lines.append("")
            lines.append("#### 4. Ограничения и доказательная база (Evidence)")
            lines.append(
                f"- Выводы основаны на детерминированном расчёте EPANET 2.2 (проект `{ctx.project.name}`, статус `{an.status}`)."
            )
            return "\n".join(lines)

        # General header for what_happens, find_problems, why_happened, generate_report, ask_question
        mode_titles = {
            "what_happens": "Обзор текущего состояния экрана и расчёта («Что происходит?»)",
            "find_problems": "Диагностика аномалий и узких мест сети («Найти проблемы»)",
            "why_happened": "Причинно-следственный анализ гидравлического режима («Почему это произошло?»)",
            "generate_report": f"Инженерный отчёт по расчёту сети «{ctx.project.name}»",
            "ask_question": f"Ответ на инженерный запрос: «{user_question or 'Анализ состояния модели'}»",
        }
        lines.append(f"### {mode_titles.get(mode, 'Инженерный анализ EPANET 2.2')}")
        lines.append("")

        # Section 1: Observations
        lines.append("#### 1. Наблюдение (Факты расчёта)")
        lines.append(
            f"- **Конфигурация сети `{ctx.project.name}`**: расчётных узлов — `{net.junctions}`, резервуаров — `{net.reservoirs}`, "
            f"баков — `{net.tanks}`, трубопроводов — `{net.pipes}`, насосов — `{net.pumps}`, клапанов — `{net.valves}`. "
            f"Тип расчёта: `{an.type}` (длительность `{an.duration_h} ч`, текущий срез `t = {an.active_time_h} ч`, статус: `{an.status}`)."
        )
        if vp.get("is_zoomed_subregion"):
            lines.append(
                f"- **Видимая область экрана (Viewport)**: пользователь приблизил участок, содержащий `{vp.get('visible_nodes_count')}` узлов "
                f"и `{vp.get('visible_links_count')}` участков (аномалий на экране: `{vp.get('visible_alerts_count')}`)."
            )
        lines.append(
            f"- **Ключевые показатели (KPI сети)**:\n"
            f"  - Минимальный свободный напор: [Узел {kpi.min_pressure_node}: min_pressure_m = {kpi.min_pressure_m} м]\n"
            f"  - Максимальный свободный напор: [Узел {kpi.max_pressure_node}: max_pressure_m = {kpi.max_pressure_m} м]\n"
            f"  - Суммарный водоразбор: [Сеть {ctx.project.name}: total_demand_lps = {kpi.total_demand_lps} л/с]\n"
            f"  - Максимальная скорость потока: [Труба {kpi.max_velocity_pipe}: max_velocity_mps = {kpi.max_velocity_mps} м/с]\n"
            f"  - Максимальный гидравлический уклон: [Труба {kpi.max_headloss_pipe}: max_headloss_m_per_km = {kpi.max_headloss_m_per_km} м/км]"
        )

        if alerts:
            lines.append(f"- **Выявленные отклонения и аномалии (всего `{kpi.alerts_count}`, показаны Top-{len(alerts)})**:")
            for idx, al in enumerate(alerts, 1):
                lines.append(
                    f"  {idx}. **[{al.severity.upper()}]** [{al.object_type} {al.object}: {al.metric_name} = {al.value} {al.unit} "
                    f"(порог {al.threshold} {al.unit})] — {al.description}"
                )
        else:
            lines.append("- **Отклонения**: на текущем шаге расчёта нарушений пороговых значений давлений и скоростей не зафиксировано.")

        # Section 2: Probable engineering cause
        lines.append("")
        lines.append("#### 2. Вероятная инженерная причина (на основе связей и расчёта)")
        if nb and nb.get("connected_links"):
            f_obj = nb.get("focus_object", sel.id)
            lines.append(
                f"- **Анализ гидравлического тракта вокруг фокусного объекта `{f_obj}`**:"
            )
            for c in nb["connected_links"][:5]:
                lines.append(
                    f"  - Участок `{c['link_id']}` (поток `{c['actual_flow_from']}` → `{c['actual_flow_to']}`, диаметр `{c['diameter_mm']} мм`, "
                    f"длина `{c['length_m']} м`): пропускает расход `{c['flow_lps']} л/с` со скоростью `{c['velocity_mps']} м/с`, "
                    f"создавая удельный уклон `{c['headloss_m_per_km']} м/км` и суммарную потерю напора `ΔH = {c['total_headloss_m']} м`."
                )
        if ctx.applicable_rules:
            for rule in ctx.applicable_rules[:3]:
                lines.append(f"- **{rule['title']}**: {rule['explanation']}")
                for cause in rule.get("typical_causes", [])[:2]:
                    lines.append(f"  - Возможный фактор: {cause}.")
        else:
            lines.append(
                f"- Распределение напоров определяется балансом подачи от источников (напор в узле максимального давления "
                f"`{kpi.max_pressure_node}` составляет `{kpi.max_pressure_m} м`) и потерями трения в магистралях (максимальный уклон "
                f"на участке `{kpi.max_headloss_pipe}` равен `{kpi.max_headloss_m_per_km} м/км`)."
            )

        # Section 3: Recommendations
        lines.append("")
        lines.append("#### 3. Инженерные рекомендации")
        if ctx.applicable_rules:
            for rule in ctx.applicable_rules[:3]:
                for rec in rule.get("recommendations", []):
                    lines.append(f"- {rec} (рекомендация для проверки расчётом сценария).")
        else:
            lines.append(
                f"- Проверить работу участка `{kpi.max_headloss_pipe}` с наибольшим гидравлическим уклоном (`{kpi.max_headloss_m_per_km} м/км`) "
                f"в часы максимального водоразбора."
            )
            lines.append(
                "- При необходимости оценить динамику наполнения/опорожнения резервуаров и баков на 24-часовом горизонте."
            )

        # Section 4: Limitations & Evidence
        lines.append("")
        lines.append("#### 4. Ограничения расчёта и доказательная база (Evidence)")
        lines.append(
            "- Выводы сформированы без угадывания по изображению, строго по численным данным решателя EPANET 2.2."
        )
        lines.append(
            "- Рекомендации носят консультативный характер и требуют верификации путём запуска сравнительного сценария («Сравнить сценарии»)."
        )
        return "\n".join(lines)
