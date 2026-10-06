# Структура проекта

```
epanet-ai/
├── README.md                     # быстрый старт
├── requirements.txt
├── configs/                      # ВСЕ настройки, менять только здесь
│   ├── dataset.yaml              # режим EPANET (PDA), состав неисправностей, бюджеты контекста,
│   │                             # правила валидации, разбиение train/val/test
│   ├── thresholds.yaml           # нормативы (давление/скорость/уровни/недоподача) — единственный
│   │                             # источник порогов для Analytics и для LLM
│   ├── labels.yaml               # словарь категорий, severity, уверенности, «проверок»
│   └── experts.yaml              # кто размечает, размер партий, доля двойной разметки
│
├── schemas/                      # контракты данных (JSON Schema)
│   ├── scenario.schema.json
│   ├── case.schema.json
│   └── screen.schema.json        # результат «что находится на экране»
│
├── src/
│   ├── common.py                 # пути, чтение/запись json/jsonl/yaml, хеши, seed
│   ├── analytics.py              # Analytics Engine: KPI, алерты, Top-K, evidence, сравнение сценариев
│   ├── context_builder.py        # Context Builder: llm_context.json по режимам и бюджетам
│   ├── prompt_templates/         # system/user промпты (версионируются)
│   ├── generate/
│   │   ├── run_scenarios.py      # генератор сценариев: сеть + неисправности → EPANET → CSV
│   │   └── build_derived_all.py  # прогон Analytics + Context по всем сценариям
│   ├── dataset/
│   │   ├── build_cases.py        # сценарий → кейсы (вопросы, факты, пустой gold)
│   │   ├── make_batches.py       # кейсы → партии для инженеров (+двойная разметка)
│   │   ├── make_expert_pack.py   # партия → HTML-форма для инженера (офлайн)
│   │   ├── expert_pack_template.html
│   │   ├── import_expert_json.py # выгрузки инженеров → data/cases/filled
│   │   ├── validate_cases.py     # схема + ссылки E-xxx + числа + длина
│   │   ├── check_quality.py      # IQA (согласие экспертов), статистика датасета
│   │   └── export_instruct.py    # filled → train/val/test.jsonl + eval_test.jsonl
│   ├── vision/
│   │   ├── detect_screen.py      # скриншот → JSON «что на экране» (OCR + правила, без CV-модели)
│   │   ├── screen_to_context.py  # экран + расчёт → llm_context.request.ui или уточняющий вопрос
│   │   └── schema.py             # валидатор результата
│   ├── train/
│   │   └── qlora_sft.py          # QLoRA-SFT (GPU): chat-формат, маскирование лосса, run.json
│   └── eval/
│       ├── metrics_offline.py    # состояние датасета до обучения
│       ├── metrics_model.py      # бенчмарк модели: fact accuracy, галлюцинации, latency, VRAM
│       └── metrics_screen.py     # метрики понимания экрана (объект, значения, уточнения)
│
├── data/                         # ТОЛЬКО реальные данные (см. data/README.md)
│   ├── raw/                      # исходные реальные сети (.inp)
│   ├── scenarios/                # расчёты по этим сетям
│   ├── cases/                    # pending → inbox → filled
│   ├── batches/                  # партии и назначения инженеров
│   ├── engineer_forms/           # xlsx-формы (генерируются tools/make_excel_form.py)
│   ├── screen_labels/            # разметка реальных скриншотов + screenshots/
│   ├── collected/                # забранное с сервиса разметки (cases/, models/)
│   ├── splits/                   # датасеты обучения
│   └── eval/                     # отчёты: валидация, качество, метрики
├── tests/fixtures/               # синтетика ТОЛЬКО для автотестов (в обучение не идёт)
│   ├── networks/vn01_demo.inp    # демо-сеть для проверки конвейера
│   └── screen_demo/              # синтетические OCR-блоки для метрик зрения
│
├── service/                      # сервис сбора данных от инженеров (см. docs/10)
│   ├── app.py · storage.py · conversion.py · modeling.py · quality.py · export.py
│   ├── static/{index.html, admin.html}   # интерфейс инженера и админка
│   └── vendor/emc/               # ETL-модули EPANET-Model-Cleaner (MIT, без GUI)
├── deploy/                       # Dockerfile, compose, Caddyfile, install_vps.sh, backup.sh
├── service_data/                 # данные сервиса: БД, загрузки, модели, экспорты (в git не нужны)
│
├── tools/
│   ├── ExpertCasePack_*.html     # готовые формы для инженеров (открыть в браузере)
│   ├── make_examples.py          # 3 эталонных примера разметки
│   ├── simulate_expert_export.py # автотест конвейера разметки (НЕ данные для обучения)
│   ├── make_excel_form.py        # генерация xlsx-формы
│   ├── label_screen.html         # офлайн-разметчик скриншотов для бенчмарка зрения
│   ├── check_data_purity.py      # проверка: не попала ли синтетика в датасет
│   └── run_pipeline.sh           # весь конвейер одной командой
│
└── docs/                         # 01 проект · 02 данные · 03 генерация · 04 обучение ·
                                  # 05 бенчмарк · 06 задания инженерам · 07 конвейер
```

## Разделение ответственности

| Роль | Зона работ | Артефакты |
|---|---|---|
| Разработчик AI-модуля | генерация, аналитика, контекст, обучение, бенчмарк | `src/`, `configs/`, `data/splits` |
| Инженер (внешняя сеть) | загружает свою модель и размечает её на сайте | `service/` → `data/collected/` |
| Инженер-гидравлик | разметка сценариев, золотые ответы | `data/cases/inbox/*.json` |
| Ведущий инженер | ревью, согласованность, сложные кейсы | `review_status`, `check_quality` |
| Продукт/эксплуатация | приёмочные критерии, SLA | `docs/05_EVAL_BENCHMARK.md` |

## Принципы, которые нельзя нарушать

1. **LLM не считает.** Любое число в ответе модели существует в `llm_context` (и имеет `E-xxx`).
2. **Truth отделён.** `scenario.truth` не попадает в контекст модели ни в одном режиме.
3. **Разбиение по сценариям.** Один расчёт целиком попадает в один из сплитов.
4. **Разметка слепая.** Инженер заполняет ответ до того, как увидит внесённую неисправность.
5. **Воспроизводимость.** Все сценарии пересоздаются из `.inp` + `configs` + `seed`.
6. **Зрение — детерминированное.** Пиксели в LLM не уходят: только структурированные факты
   об экране (`ui`-блок), и если объект определён ненадёжно — ассистент спрашивает, а не угадывает.
7. **Только реальные данные.** В `data/` нет синтетики; генератор и демо-сеть используются
   как тестовый стенд (`tests/fixtures/`), а `export_instruct` по умолчанию отсекает синтетические
   кейсы. Аугментация — отдельный осознанный шаг с явным флагом.
