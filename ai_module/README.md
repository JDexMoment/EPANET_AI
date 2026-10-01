# EPANET 2.2 AI Module — архитектура, данные, обучение и эксплуатация

> Полное руководство по локальному ИИ-ассистенту для EPANET 2.2 (Qwen3 4B/8B, Data-first).
> Соответствует дорожной карте из `roadmap.pdf`.

---

## 1. Что уже реализовано в этом репозитории

| Слой | Файл | Что делает |
|------|------|------------|
| **Delphi UI** | `Delphi_GUI/epanet2w/Fmain.pas` | Кнопка **«AI»** на панели инструментов + меню **«AI Ассистент»** с 7 режимами |
| **Delphi UI** | `Delphi_GUI/epanet2w/Fmap.pas` | Пункты правого клика по карте: «AI: Объяснить объект», «AI: Почему это произошло?» |
| **Delphi UI** | `Delphi_GUI/epanet2w/Fai_assistant.pas` | Окно ассистента: кнопки режимов, поле вопроса, вывод ответа, кнопка «Открыть отчёт» |
| **Delphi Bridge** | `Delphi_GUI/epanet2w/Uai_bridge.pas` | Context Collector: собирает экран, выделение, zoom-окно, период времени; экспортирует `.INP`; шлёт JSON в локальный сервис |
| **Engine** | `ai_module/engine_adapter/ctypes_epanet.py` | Прямой вызов C-движка EPANET 2.2 через `ctypes`, пошаговая гидравлика + качество, нормализация в СИ |
| **Analytics** | `ai_module/analytics/engineering_engine.py` | Детерминированные KPI, пороговые алерты, топологический обход, анализ viewport |
| **Analytics** | `ai_module/analytics/scenario_comparator.py` | Детерминированное сравнение двух расчётов (дельты давлений, скоростей, изменённые параметры) |
| **Knowledge/RAG** | `ai_module/knowledge_rag/knowledge_base.py` | Нормы, правила интерпретации, типовые причины и рекомендации по категориям аномалий |
| **Context** | `ai_module/context/context_builder.py` | Собирает компактный JSON-контекст для LLM (Roadmap §5) + разделение на 3 JSON для датасета (Roadmap §9) |
| **LLM** | `ai_module/llm/qwen_client.py` | Сменный бэкенд: Ollama / vLLM / llama.cpp / HF+LoRA / детерминированный синтезатор |
| **LLM** | `ai_module/llm/prompts.py` | System-prompt с жёсткими правилами анти-галлюцинаций + инструкции по 7 режимам |
| **Reports** | `ai_module/reports/report_generator.py` | Отчёты Markdown + HTML с жёстким разделением «факты EPANET» / «интерпретация AI» |
| **API** | `ai_module/api/app.py` | FastAPI: `/api/v1/health`, `/api/v1/analyze`, `/api/v1/context`, `/api/v1/report` |
| **Training** | `ai_module/training/generate_dataset.py` | Генератор сценариев и SFT-датасета (ChatML JSONL) из `.INP` файлов |
| **Training** | `ai_module/training/validate_dataset.py` | Quality-gate: полнота, структура, анти-галлюцинации, покрытие всех 7 режимов |
| **Training** | `ai_module/training/train_qlora.py` | QLoRA/LoRA дообучение Qwen3-4B/8B на подготовленном датасете |
| **Training** | `ai_module/training/benchmark.py` | Бенчмарк: fact accuracy, hallucination rate, precision/recall, latency, throughput |
| **Tests** | `ai_module/tests/` | 29 тестов: движок, аналитика, LLM, отчёты, API end-to-end |

---

## 2. Архитектура потока данных

```
┌──────────────────────────── Delphi EPANET2W (Windows) ────────────────────────────┐
│  Кнопка «AI» / меню «AI Ассистент» / правый клик по карте                          │
│        │                                                                            │
│        ▼                                                                            │
│  Uai_bridge.BuildUIContextJSON                                                      │
│    • selection (выбранный объект из Browser/PropertyEditor)                        │
│    • viewport bbox + список видимых узлов/труб (что реально на экране)              │
│    • simulation_state (current_period, Nperiods, RunFlag)                          │
│    • экспорт текущей сети → TempDir/epanet_ai_snapshot.inp                         │
│    • скриншот карты → TempDir/epanet_ai_viewport.bmp                               │
│        │  POST /api/v1/analyze                                                      │
└────────┼──────────────────────────────────────────────────────────────────────────┘
         ▼
┌─────────────────── Python AI Service (127.0.0.1:8765) ────────────────────────────┐
│  1. EpanetEngineAdapter.run_simulation(inp)  → детерминированный расчёт            │
│  2. EngineeringAnalyticsEngine.analyze(...)  → KPI, alerts, топология, viewport    │
│  3. [compare_inp_file] → ScenarioComparator                                       │
│  4. KnowledgeBase.retrieve_relevant_rules(...)  → нормы/причины/рекомендации       │
│  5. ContextBuilder → LLMContextPayload (компактный JSON, Roadmap §5)               │
│  6. QwenClient.generate(...)  → Qwen3 4B/8B (или детерминированный синтезатор)     │
│  7. ReportGenerator.save_report(...)  → Markdown + HTML (для режима «отчёт»)       │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Ключевой принцип (Roadmap §8): LLM никогда не считает гидравлику.** Все числа приходят из
детерминированного слоя (C-движок EPANET + Python-аналитика). Модель отвечает только за
интерпретацию, объяснение причин, формулировки рекомендаций и генерацию отчёта.

---

## 3. Быстрый старт (10 минут)

### 3.1. Установка Python-окружения

```bash
cd EPANET_AI
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

pip install -r ai_module/requirements.txt
```

### 3.2. Проверка, что C-движок EPANET собирается

```bash
python -c "from ai_module.engine_adapter.ctypes_epanet import EpanetEngineAdapter; \
a = EpanetEngineAdapter(); print(a.lib_path)"
```

Должно напечатать путь к `libepanet2.so` (Linux) или `epanet2.dll` (Windows).
Если компилятора нет — используйте готовый `epanet2.dll` из дистрибутива EPANET и передайте путь:
```python
EpanetEngineAdapter(lib_path=r"C:\EPANET\epanet2.dll")
```

### 3.3. Запуск локального AI-сервиса

```bash
python -m ai_module.run_service
# или Windows: двойной клик по start_ai_service.bat
```

Проверка:
```bash
curl http://127.0.0.1:8765/api/v1/health
```

Тестовый запрос:
```bash
curl -X POST http://127.0.0.1:8765/api/v1/analyze ^
  -H "Content-Type: application/json" ^
  -d "{\"mode\":\"what_happens\",\"inp_file\":\"C:/EPANET_AI/ai_module/data/raw_networks/city_district_si.inp\",\"simulation_state\":{\"current_period\":12}}"
```

### 3.4. Сборка Delphi GUI с кнопкой «AI»

1. Откройте `Delphi_GUI/components/Epa.dpk` → **Install** (нужно до открытия проекта).
2. Откройте `Delphi_GUI/epanet2w/Epanet2w.dproj` в Delphi 10/11/12 (Community Edition подходит).
3. В `Epanet2w.dpr` уже добавлены `Uai_bridge` и `Fai_assistant` — ничего добавлять не нужно.
4. **Build** (не Run). Рядом с `epanet2w.exe` положите `epanet2.dll` (из `SRC_engines`).
5. Запустите `epanet2w.exe`, откройте `.INP`/`.NET`, нажмите **Run Analysis**, затем кнопку **«AI»**.

> **Важно:** Python-сервис должен быть запущен **до** нажатия кнопки «AI».
> В продакшене это будет фоновый сервис/launcher, стартующий вместе с EPANET.

---

## 4. Куда класть данные для обучения и как они должны выглядеть

### 4.1. Папки данных

```
ai_module/data/
├── raw_networks/        ← СЮДА кладём .INP файлы реальных/учебных сетей
│   ├── city_district_si.inp       (демо: базовая сеть с дефицитом напора)
│   ├── city_district_upgraded.inp (демо: тот же район после реконструкции труб)
│   └── tutorial.inp               (пример из User Manual EPANET)
├── scenarios/           ← АВТОМАТИЧЕСКИ генерируется (13 сценариев из 3 сетей)
│   └── scenario_0001/
│       ├── project_context.json   (Roadmap §9: параметры расчёта и состояние экрана)
│       ├── analysis_results.json  (Roadmap §9: фактические результаты EPANET)
│       ├── derived_metrics.json   (Roadmap §9: KPI, алерты, граф связей)
│       ├── qa_annotations.json    (question / gold_answer / severity / category / evidence / report)
│       └── gold_report.md         (эталонный полный отчёт)
├── sft_datasets/        ← АВТОМАТИЧЕСКИ: train/val/benchmark JSONL (ChatML)
└── benchmarks/          ← АВТОМАТИЧЕСКИ: отчёты бенчмарков
```

### 4.2. Требования к `.INP` файлам в `raw_networks/`

- Обязательна секция **`[COORDINATES]`** — иначе координаты сгенерируются автоматически (сетка),
  и режим «Что происходит на экране» будет менее точным.
- Желательна секция **`[PATTERNS]`** + `[TIMES]` с длительностью ≥ 24 ч — это даёт суточную динамику
  (минимумы/максимумы давлений), без неё `time_series_summary` выродится.
- Разнообразие: **US-единицы и SI-единицы**, разные `[OPTIONS] Units`, с и без насосов,
  с клапанами PRV/FCV, с танками и резервуарами. Чем разнообразнее, тем лучше обобщение.

### 4.3. Формат трёх JSON-файлов (Roadmap §9)

**`project_context.json`** — «входные условия и состояние экрана»:
```json
{
  "project":   {"name": "city_district_si", "scenario": "current_screen", "flow_units_native": "LPS", "normalized_units": "SI (m, L/s, m/s, mm)"},
  "analysis":  {"type": "extended_period", "duration_h": 24.0, "step_h": 1.0, "active_period": 12, "active_time_h": 12.0, "status": "converged"},
  "selection": {"type": "junction", "id": "J-104"},
  "network_summary": {"junctions": 6, "pipes": 8, "pumps": 0, "tanks": 1, "reservoirs": 1, "valves": 0},
  "viewport":  {"is_zoomed_subregion": false, "visible_nodes_count": 8, "visible_links_count": 8}
}
```

**`analysis_results.json`** — «сырые результаты EPANET»:
```json
{
  "active_period": 12,
  "active_time_h": 12.0,
  "nodes": {"J-104": {"demand_lps": 20.0, "head_m": 127.41, "pressure_m": -1.09, "quality": 0.0}, "...": {}},
  "links": {"P-104": {"flow_lps": 28.0, "velocity_mps": 1.16, "headloss_m_per_km": 15.77, "status": "OPEN"}, "...": {}},
  "topology": {"nodes": [...], "links": [...]}
}
```

**`derived_metrics.json`** — «инженерные признаки»:
```json
{
  "kpi": {"min_pressure_m": -1.09, "min_pressure_node": "J-104", "max_pressure_m": 41.68,
          "max_pressure_node": "J-101", "total_demand_lps": 99.5, "max_velocity_mps": 1.815,
          "max_velocity_pipe": "P-101", "max_headloss_m_per_km": 15.77, "max_headloss_pipe": "P-104",
          "alerts_count": 2},
  "alerts": [{"type": "negative_pressure", "severity": "critical", "object_type": "junction",
              "object": "J-104", "metric_name": "pressure_m", "value": -1.09,
              "threshold": 0.0, "unit": "m", "description": "Отрицательное давление..."}],
  "selected_object_details": {"object_class": "node", "id": "J-104", "type": "junction",
                              "elevation_m": 128.5, "base_demand_lps": 20.0,
                              "current_state": {...}, "time_series_summary": {...}},
  "topological_neighborhood": {"focus_object": "J-104", "connected_links": [...], "adjacent_nodes": {...}},
  "scenario_comparison": null
}
```

**`qa_annotations.json`** — размеченные инженерные ситуации (это и есть «золотые» ответы):
```json
[{
  "sample_id": "scenario_0003_find_problems",
  "scenario_id": "scenario_0003",
  "mode": "find_problems",
  "question": "Найди все инженерные проблемы и аномалии...",
  "gold_answer": "### Диагностика аномалий... #### 1. Наблюдение (Факты расчёта)...",
  "severity": "critical",
  "category": "negative_pressure",
  "evidence": [{"object": "J-104", "object_type": "junction", "metric": "pressure_m",
                "value": -1.09, "unit": "m", "threshold": 0.0}],
  "report": "..."
}]
```

### 4.4. Формат SFT-датасета (ChatML JSONL)

`ai_module/data/sft_datasets/train_qwen3_chatml.jsonl` — одна строка = один sample:
```json
{
  "id": "scenario_0003_find_problems",
  "scenario_id": "scenario_0003",
  "mode": "find_problems",
  "severity": "critical",
  "category": "negative_pressure",
  "evidence": [...],
  "messages": [
    {"role": "system",    "content": "Ты — локальный ИИ-ассистент инженера-гидравлика... НЕ ВЫДУМЫВАЙ..."},
    {"role": "user",      "content": "### ЗАДАНИЕ (find_problems)... ### МАШИНОЧИТАЕМЫЙ КОНТЕКСТ (JSON) ```json {...} ```"},
    {"role": "assistant", "content": "### Диагностика... #### 1. Наблюдение (Факты расчёта)..."}
  ]
}
```

### 4.5. Как добавить свои данные и перегенерировать датасет

```bash
# 1. Скопировать свои сети
copy C:\my_models\net_01.inp  ai_module\data\raw_networks\
copy C:\my_models\net_02.inp  ai_module\data\raw_networks\

# 2. Перегенерировать сценарии + SFT-датасет (4 временных среза на каждую сеть)
python -m ai_module.training.generate_dataset --max-periods 4

# 3. Проконтролировать качество (обязательно должно быть PASSED)
python -m ai_module.training.validate_dataset
```

**Целевые объёмы (Roadmap §9):**
| Этап | Кол-во размеченных сценариев | Что это значит в файлах |
|------|------------------------------|--------------------------|
| Первый прототип | 200–500 | ~20–60 `.INP` × 5 режимов × несколько срезов |
| Устойчивый fine-tuning | 1 000–5 000+ | 150–700 `.INP` + реальные вопросы из UI |

---

## 5. Как обучать модель (Qwen3 4B / 8B)

### 5.1. Этап 0 — без обучения (уже работает)

Бэкенд `deterministic_pilot` даёт эталонные инженерные ответы с 100% факт-точностью.
Это позволяет запустить UI и накопить **реальные** вопросы пользователей ещё до всякого fine-tuning.

### 5.2. Этап 1 — установка LLM-рантайма

**Вариант A. Ollama (самый простой, рекомендуется для старта):**
```bash
# Установить Ollama, затем:
ollama pull qwen3:4b          # быстрый edge-вариант
ollama pull qwen3:8b          # предпочтительный пилот (Roadmap §13)
```
```bash
# Windows
set EPANET_AI_BACKEND=ollama
set EPANET_AI_OLLAMA_MODEL=qwen3:8b
python -m ai_module.run_service
```

**Вариант B. vLLM / llama.cpp (OpenAI-совместимый сервер):**
```bash
set EPANET_AI_BACKEND=openai_compat
set EPANET_AI_LLM_URL=http://127.0.0.1:8000/v1
set EPANET_AI_MODEL=Qwen/Qwen3-8B
python -m ai_module.run_service
```

**Вариант C. Локальный HuggingFace + LoRA (для инференса с вашими весами):**
```bash
pip install torch transformers peft accelerate
set EPANET_AI_BACKEND=hf_local
set EPANET_AI_MODEL=Qwen/Qwen3-8B
set EPANET_AI_LORA_PATH=ai_module/training/checkpoints/qwen3-epanet-lora
python -m ai_module.run_service
```

### 5.3. Этап 2 — бенчмарк ДО обучения (Roadmap §12)

```bash
python -m ai_module.training.benchmark --backend ollama --model-name qwen3:8b --limit 85
python -m ai_module.training.benchmark --backend deterministic_pilot --limit 85
```

Сравните `fact_accuracy`, `hallucination_rate`, `avg_latency_ms` — это baseline.
Сохраняйте отчёты из `ai_module/data/benchmarks/` — они нужны для сравнения «до/после».

### 5.4. Этап 3 — QLoRA дообучение

**Требования:** NVIDIA GPU с ≥ 16 GB VRAM (4-bit QLoRA, Qwen3-8B).
Для Qwen3-4B хватит 10–12 GB. На CPU — возможно, но медленно (`--no-4bit`).

```bash
pip install torch transformers datasets peft trl accelerate bitsandbytes

# Qwen3-4B (edge)
python -m ai_module.training.train_qlora --base-model Qwen/Qwen3-4B --epochs 3

# Qwen3-8B (пилот)
python -m ai_module.training.train_qlora --base-model Qwen/Qwen3-8B --epochs 3 --batch-size 1 --grad-accum 16
```

Результат: `ai_module/training/checkpoints/qwen3-epanet-lora/` (только адаптер ~50–200 MB).
Далее инференс через Вариант C (§5.2) — базовая модель + LoRA-адаптер.

### 5.5. Этап 4 — бенчмарк ПОСЛЕ обучения и решение

```bash
python -m ai_module.training.benchmark --backend hf_local --model-name Qwen3-8B+LoRA --limit 85
```

Критерии приёмки (Roadmap §12):
- `fact_accuracy` ≥ 0.95 (цель — 1.0, как у детерминированного слоя)
- `hallucination_rate` ≤ 0.05
- `problem_recall` ≥ 0.85
- `report_completeness` ≥ 0.90
- `avg_latency_ms` — допустимо для UI (< 10 с), иначе берите 4B или квантование

---

## 6. Режимы AI-ассистента (7 штук)

| Режим | ID | Что делает | Источник данных |
|-------|----|------------|-----------------|
| Что происходит? | `what_happens` | Обзор видимого участка + KPI + отклонения | `viewport_context` + `kpi` + `alerts` |
| Объяснить объект | `explain_object` | Параметры, суточная динамика, роль в кольце | `selected_object_details` + `topological_neighborhood` |
| Найти проблемы | `find_problems` | Все аномалии по критичности | `alerts` + `applicable_rules` |
| Почему это произошло? | `why_happened` | Причинно-следственный разбор | `topological_neighborhood` + `rules.typical_causes` |
| Составить отчёт | `generate_report` | Полный отчёт Markdown/HTML | всё + `ReportGenerator` |
| Сравнить сценарии | `compare_scenarios` | Дельта двух расчётов | `scenario_comparison` |
| Ответить на вопрос | `ask_question` | Свободный вопрос по модели | всё |

---

## 7. Настройка порогов (инженерные нормы)

Файл `ai_module/config/settings.py`:
```python
DEFAULT_THRESHOLDS = {
    "min_pressure_warning_m": 15.0,
    "min_pressure_critical_m": 10.0,
    "negative_pressure_m": 0.0,
    "max_pressure_warning_m": 60.0,
    "max_pressure_critical_m": 75.0,
    "max_velocity_warning_mps": 2.5,
    "max_velocity_critical_mps": 3.5,
    "min_velocity_stagnation_mps": 0.05,
    "max_headloss_m_per_km": 15.0,
    "top_n_alerts": 10,
}
```
Файл `ai_module/config/rules_and_norms.json` — тексты правил, типовые причины и рекомендации.
Их можно адаптировать под местные нормативы (СП, DVGW, local utility standards) — LLM подхватит автоматически.

---

## 8. Тесты и регрессия

```bash
python -m pytest ai_module/tests -q          # 29 тестов
python -m ai_module.training.validate_dataset  # quality-gate датасета
```

Перед каждым коммитом:
```bash
python -m pytest ai_module/tests -q && python -m ai_module.training.validate_dataset
```

---

## 9. Что делать дальше (по Roadmap §11)

| Этап | Статус | Следующий шаг |
|------|--------|---------------|
| 1. Сценарии, KPI, критерии | ✅ | Расширить `raw_networks` реальными моделями заказчика |
| 2. Прототип Data-first | ✅ | Подключить Qwen3-8B через Ollama, сравнить с `deterministic_pilot` |
| 3. Context Builder, structured output, шаблоны | ✅ | История запросов в PostgreSQL/SQLite; evidence-links в UI |
| 4. Dataset + LoRA + benchmark | ✅ (скелет) | Накопить 500+ реальных сценариев из UI, дообучить |
| 5. Agent/tool mode | ⏳ | Дать Qwen3 инструменты вызова аналитики (с песочницей и правами) |
| 6. Мониторинг, model registry, offline | ⏳ | Версионирование моделей, regression-тесты, офлайн-инсталлятор |

---

## 10. Частые проблемы

| Симптом | Причина | Решение |
|---------|---------|---------|
| Delphi: «Не удалось подключиться к локальному AI-сервису» | Python-сервис не запущен | `python -m ai_module.run_service` или `start_ai_service.bat` |
| `OSError: cannot load library` | Не найден `epanet2.dll` / `libepanet2.so` | Положить DLL рядом с `epanet2w.exe`; для Python — скомпилировать или указать `lib_path` |
| Давления выглядят нереально | В `.INP` единицы не те, что ожидались | Проверить `[OPTIONS] Units`; адаптер нормализует автоматически |
| Модель «выдумывает» числа | Не тот режим / нет grounding | Убедиться, что ответ содержит ссылки `[Узел X: ...]`; увеличить `top_n_alerts`; не понижать `temperature` |
| OOM при QLoRA | Мало VRAM | `--no-4bit` отключить нельзя — наоборот, уменьшить `--max-seq-length`, `--batch-size 1`, `--lora-r 8` |
| Датaset validation FAILED | Непокрытый режим / неподтверждённое число | Посмотреть `problems` в отчёте валидатора |
