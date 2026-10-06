# Структура обучающих данных

## 0. Три уровня данных

```
SCENARIO (расчёт EPANET)          ──▶  CASE (инженерная ситуация)   ──▶  SAMPLE (пример для SFT)
сеть + правки + результаты              вопрос + факты + золотой ответ      chat-сообщения train.jsonl
data/scenarios/<scenario_id>/           data/cases/filled/<case_id>.json    data/splits/*.jsonl
```

Оценка объёмов (roadmap п.9):
| Уровень | Прототип | Устойчивый fine-tuning |
|---|---|---|
| Сценарии (расчёты) | 20–30 | 100–300 |
| Кейсы (ситуации) | 200–500 | 1 000–5 000+ |
| Примеры SFT | то же | то же + structured-вариант |

Один сценарий даёт 5–6 кейсов (режимы «Что происходит», «Найти проблемы», «Почему», «Объяснить объект»,
«Сравнить сценарии», «Составить отчёт»).

## 1. Сценарий (scenario) — «сырьё»

Каталог: `data/scenarios/<scenario_id>/`

```
vn01__pipe_roughness_drop__P106__055/
├── scenario.json          # метаданные + правки модели + ground truth
├── network.inp            # сеть после правок (то, что реально считалось)
├── results/
│   ├── pressure.csv       # узлы × время (индекс — ЧАСЫ), м вод.ст.
│   ├── head.csv
│   ├── demand.csv         # м³/с (в отчётах умножается на 1000 → л/с)
│   ├── flowrate.csv       # м³/с
│   ├── velocity.csv       # м/с
│   └── link_status.csv    # 1 = открыт, 0 = закрыт
└── derived/
    ├── derived_metrics.json   # KPI, алерты, Top-проблемы, сравнение с базовым расчётом
    ├── evidence.json          # словарь фактов: E-001 … (единственный источник чисел для LLM)
    └── llm_context_<mode>.json# замороженный контекст для каждого режима (то, что видит модель)
```

Схема `scenario.json`: `schemas/scenario.schema.json`.
Поле `truth` (что внесено генератором) **никогда** не попадает в контекст модели —
оно используется только для проверки качества разметки и для метрик бенчмарка.

Идентификатор: `<сеть>__<тип_неисправности>__<объект>__<масштаб>`, например
`vn01__demand_increase__J105__225` = сеть vn01, рост спроса в J-105 в 2,25 раза.

## 2. Кейс (case) — единица разметки и обучения

Файл: `data/cases/filled/<case_id>.json` (до разметки — в `data/cases/pending/`).
Схема: `schemas/case.schema.json`.

```jsonc
{
  "case_id": "c_vn01__demand_increase__J105__225__make_report__05",
  "scenario_id": "vn01__demand_increase__J105__225",
  "mode": "make_report",            // whats_happening | explain_object | find_problems |
                                    // why_happened | make_report | compare_scenarios | ask
  "question": "Составьте инженерный отчёт по этому расчёту.",
  "selection": {"type": "whole_network", "id": null},

  "facts": {                        // ЗАМОРОЖЕННЫЙ срез аналитики
    "context_digest": "3f9c…",      // sha256 контекста: фиксирует, что видел инженер
    "llm_context_ref": "data/scenarios/…/llm_context_make_report.json",
    "evidence": [                   // факты, на которые можно ссылаться
      {"evidence_id": "E-002", "object": "J-105", "metric": "pressure",
       "value": 9.96, "unit": "м вод.ст.", "time_h": 18.0,
       "threshold_rule": "low_pressure_critical",
       "statement": "J-105: давление 9.96 м вод.ст. в 18 ч (норматив 10.0 м); ниже норматива 1 из 25 шагов расчёта (≈1 ч)"}
    ]
  },

  "label": {                        // цель №1 (классификация ситуации)
    "has_problem": true,
    "category": "demand_anomaly",   // id из configs/labels.yaml
    "secondary_categories": ["supply_deficit"],
    "severity": "critical",
    "primary_objects": ["J-105", "P-105", "T-1"],
    "evidence_refs": ["E-002", "E-008", "E-024"],
    "confidence": "high",
    "likely_cause": "Сверхнормативный водоразбор в зоне J-105"
  },

  "gold": {                         // цель №2 (генерация текста)
    "answer": "…80–320 слов, каждое число со ссылкой (E-xxx)…",
    "answer_structured": {
      "observations": ["…"],
      "probable_causes": [{"text": "…", "confidence": "high", "check": "check_leak_survey"}],
      "checks": ["…"],
      "recommendations": ["…"],
      "limitations": ["…"],
      "evidence_refs": ["E-002"]
    },
    "report_markdown": "…только для mode=make_report…",
    "checklist": {"must_not_claim": ["порыв подтверждён"], "needs_verification": []}
  },

  "probe_questions": [ {"id": "causes", "text": "…", "answer": "…"} ],
  "annotation": { "annotator_id": "exp_01", "time_spent_min": 22, "review_status": "accepted", … },
  "eval": { "required_facts": [{"text": "…", "must_contain": ["9,96"]}],
            "forbidden_claims": ["…"], "required_sections": ["результаты", "причины"] }
}
```

### Правила, которые проверяет валидатор (`src/dataset/validate_cases.py`)

1. схема JSON;
2. заполнены `label.*` и `gold.answer`;
3. все ссылки `E-xxx` существуют в `facts.evidence`;
4. все числа в ответе подтверждаются evidence/контекстом (главная защита от выдуманных цифр);
5. длина ответа в границах `configs/dataset.yaml → validation`.

## 3. Контекст для модели (llm_context)

Схема — фактически «промпт-пакет». Поля: `scenario`, `request{ mode, question, selection }`,
`analysis`, `network_summary`, `kpi`, `thresholds`, `alerts` (Top-N), `objects_table`,
`focus` (выбранный объект + соседи + временные ряды), `baseline_delta` (что изменилось),
`evidence` (только те факты, на которые есть ссылки в алертах/дельте/KPI), `_meta` (размер, бюджет).

Бюджеты (`configs/dataset.yaml → context`): `max_alerts 12`, `max_objects_in_table 25`,
`max_series_points 25`, `neighbor_depth 1`, `max_context_chars 12000`.
Усечение детерминированное: сначала режется `objects_table`, потом алерты, потом дельта и соседи.

**Ключевой принцип:** если числа нет в `llm_context` — модель не имеет права его называть.
Поэтому все KPI, пороги и дельты попадают в контекст с ссылками `E-xxx`.

## 4. Уровень SAMPLE (то, что уходит в обучение)

`data/splits/`:

| Файл | Что внутри |
|---|---|
| `train.jsonl`, `val.jsonl`, `test.jsonl` | chat-формат: `{messages:[system, user, assistant], meta:{…}}` |
| `structured.jsonl` | тот же вход, ответ ассистента — JSON `answer_structured` |
| `eval_test.jsonl` | тест-набор для бенчмарка: контекст + эталон + `required_facts` |

Разбиение — **по сценариям** (train/val/test = 70/15/15), чтобы кейсы одного расчёта не попадали
одновременно в обучение и в тест: иначе модель просто запомнит конкретную сеть.

## 5. Куда что кладётся (шпаргалка)

| Что | Куда |
|---|---|
| новые сети (.inp) | `data/raw/` + регистрация в `NETWORKS` (`src/generate/run_scenarios.py`) |
| результаты сценариев | `data/scenarios/` (генерируется, в git не нужно) |
| кейсы до разметки | `data/cases/pending/` |
| выгрузки инженеров (входящие) | `data/cases/inbox/` |
| размеченные кейсы | `data/cases/filled/` |
| образцы формата для инженеров | `docs/examples/` (синтетические, помечены) |
| партии и формы | `data/batches/`, `tools/ExpertCasePack_*.html`, `data/engineer_forms/` |
| датасеты обучения | `data/splits/` |
| отчёты по качеству | `data/eval/` |

## 6. Происхождение данных: только реальные

Каждый кейс несёт поле `annotation.source`:

| source | Что это | Попадает в обучение |
|---|---|---|
| `collection_service` | разметка инженера на сервисе (реальная модель) | да |
| отсутствует | внутренняя разметка по реальным сетям | да |
| `pipeline_test` | автотест конвейера (`tools/simulate_expert_export.py`) | **нет** (отсекается автоматически) |
| `synthetic_example` | образцы формата из `docs/examples/` | **нет** |
| `augmented_*` | осознанная аугментация | только с флагом `--include-synthetic` |

Проверка: `python tools/check_data_purity.py`.

## 7. Эволюция схемы

Поле `schema_version` в кейсе. При изменении полей: поднять версию, обновить
`schemas/*.schema.json`, пере-сгенерировать кейсы (`build_cases.py` создаёт только новые файлы —
для пересборки удалить `data/cases/pending` и собрать заново).
