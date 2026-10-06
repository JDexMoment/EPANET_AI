# EPANET AI-модуль: подготовка данных и обучение

Репозиторий отвечает на вопрос «как получить данные и обучить локальную LLM
(**Qwen3.5-9B**, решение от 05.10.2026 — `configs/model.yaml`) объяснять инженеру результаты
расчёта EPANET» — без того, чтобы модель считала гидравлику.

**Главный принцип:** все числа считает детерминированный аналитический слой (EPANET + Analytics),
LLM отвечает только за интерпретацию и текст. Каждое число в её ответе опирается на факт
из контекста (ссылка вида `E-007`).

```
network.inp ─▶ EPANET (PDA) ─▶ Analytics (KPI, алерты, evidence) ─▶ Context Builder ─▶ LLM
                                          │                                   ▲
                                          └──▶ кейсы ─▶ инженеры-эксперты ────┘ (золотые ответы → LoRA)

скриншот интерфейса ─▶ «понимание экрана» (OCR + правила) ─▶ ui-блок контекста ─┘
```

## Быстрый старт

```bash
pip install -r requirements.txt

bash tools/run_pipeline.sh              # сценарии → аналитика → кейсы → партии → HTML-формы

# что получилось:
ls tools/ExpertCasePack_*.html          # формы для инженеров (открыть в браузере)
python -m src.eval.metrics_offline      # состояние датасета
```

Проверка полного конвейера без инженеров (автотест):

```bash
python tools/simulate_expert_export.py --batch data/batches/batch_exp_01_01.json
python -m src.dataset.import_expert_json
python -m src.dataset.validate_cases --dir data/cases/filled
python -m src.dataset.export_instruct
```

## Роли и артефакты

| Кто | Что делает | Куда смотрит |
|---|---|---|
| Инженер-гидравлик | размечает сценарии, пишет «золотые» ответы | `tools/ExpertCasePack_*.html` → `data/cases/inbox/` |
| Разработчик AI | генерация, аналитика, контекст, обучение, бенчмарк | `src/`, `configs/`, `data/splits/` |
| Ведущий инженер | ревью и согласованность разметки | `data/eval/quality_report.json` |

## Документация

| Файл | О чём |
|---|---|
| `docs/01_PROJECT_STRUCTURE.md` | структура проекта, разделение ответственности |
| `docs/02_DATASET_SPEC.md` | **структура обучающих данных**: форматы, поля, где лежат |
| `docs/03_DATA_GENERATION.md` | как генерируются сценарии и кейсы, как добавить сеть/неисправность |
| `docs/04_TRAINING.md` | обучение: QLoRA-рецепт, порядок работ, гиперпараметры, железо |
| `docs/05_EVAL_BENCHMARK.md` | метрики, пороги допуска, регрессионный набор |
| `docs/06_ENGINEER_TASKS.md` | **ТЗ для инженеров**: что делать и как присылать ответы |
| `docs/07_PIPELINE.md` | все команды конвейера и разбор частых проблем |
| `docs/08_SCREEN_UNDERSTANDING.md` | **понимание экрана**: что на экране → данные для LLM (без CV-модели) |
| `docs/09_MODELS_AND_DEPLOYMENT.md` | **решение по модели и железо клиента**: Qwen3.5-9B, резервы, сборка GGUF |
| `docs/10_COLLECTION_SERVICE.md` | **сайт сбора разметки**: инженеры загружают свои модели, данные копятся сами |
| `docs/11_LAUNCH_AND_INVITE.md` | **запуск сервиса, проверка, выдача ссылки гидравлику** |

## Понимание экрана (скриншот → данные для модели)

CV/VLM-модель не нужна: содержимое экрана определяется детерминированно (OCR + геометрия +
словари), а результат уходит обычной текстовой LLM.

```bash
python -m src.vision.detect_screen --ocr-blocks tests/fixtures/screen_demo/ocr_01.json  # демо без OCR
python -m src.vision.screen_to_context --screen data/screen_labels/pred/demo_01.json \
    --scenario data/scenarios/vn01__demand_increase__J105__225 --question "Почему упало давление?"
python -m src.eval.metrics_screen --labels tests/fixtures/screen_demo                   # метрики зрения
```

Разметка реальных скриншотов — `tools/label_screen.html` (офлайн, экспорт в `data/screen_labels/`).
Подробности и пороги: `docs/08_SCREEN_UNDERSTANDING.md`.

## Сайт сбора данных от инженеров

> Запуск, проверка и выдача доступа инженерам: **`docs/11_LAUNCH_AND_INVITE.md`** —
> персональная ссылка вида `…/?token=…` открывает интерфейс без ввода токена.
>
> ```powershell
> powershell -ExecutionPolicy Bypass -File tools\run_service.ps1        # Windows
> ```
> ```bash
> bash tools/run_service.sh                                            # Linux / macOS
> python3 tools/check_service.py --token <токен> --admin <ADMIN_TOKEN>  # проверка, работает везде
> ```

Гидравлик заходит на сайт, загружает свою модель (`.inp`, `.NET`, `.epanet`), сервис считает
расчёт и показывает KPI, алерты и факты `E-xxx`; инженер отмечает проблему, пишет эталонный
отчёт или отвечает на свой вопрос — данные с самопроверкой уходят в датасет обучения.
Сервис живёт на сервере и собирает данные без вашего участия, раз в N часов выгружая архив.

```bash
# локально
pip install -r requirements.txt
ADMIN_TOKEN=demo-admin EXPERT_TOKENS="exp01:Иван:lead" \
  python -m uvicorn service.app:app --host 0.0.0.0 --port 8080     # → http://localhost:8080

# на сервере (Ubuntu, одной командой: docker + TLS + автозапуск + бэкапы)
bash deploy/install_vps.sh epanet.example.com

# забрать собранное к себе и собрать датасет
python tools/pull_collected.py --url https://epanet.example.com --token <ADMIN_TOKEN> --pipeline
```

Подробности, настройки автономности и безопасность — `docs/10_COLLECTION_SERVICE.md`.

## Состояние данных: пусто и правильно

**Обучаемся только на реальных данных.** В репозитории нет ни одной синтетической разметки:
`data/` содержит только структуру под настоящие сети и ответы инженеров
(`data/README.md`). Всё, что нужно для проверки кода, вынесено в `tests/fixtures/`.

Проверить в любой момент:

```bash
python tools/check_data_purity.py     # покажет реальные/синтетические кейсы по каталогам
bash tools/smoke_test.sh              # проверит весь конвейер на демо-сети во временном
                                      # каталоге и уберёт его за собой (data/ остаётся пустой)
```

## Что готово в репозитории (код и инфраструктура)

- генератор сценариев и аналитический слой (KPI, алерты, факты `E-xxx`, контекст для LLM);
- конвейер разметки: кейсы → партии → HTML/Excel-формы → импорт → валидация → IQA → сплиты;
- **сервис сбора разметки** (`service/`) с приёмом `.inp/.NET/.epanet`, расчётом и автономной выгрузкой;
- разворачивание сервиса на VPS одной командой (`deploy/install_vps.sh`, Docker + TLS + бэкапы);
- подсистема понимания экрана (`src/vision/`) с метриками;
- обучение (`src/train/qlora_sft.py`, Qwen3.5-9B) и бенчмарк модели (`src/eval/metrics_model.py`);
- 3 образца формата ответов (`docs/examples/`) и демо-фикстуры (`tests/fixtures/`).

## Чего в репозитории нет (следующий шаг)

- **реальных данных** — их и не должно быть в репозитории: наполняются через сервис
  (`docs/10_COLLECTION_SERVICE.md`) или внутреннюю разметку (`docs/06_ENGINEER_TASKS.md`);
- прогнанного обучения (нужна машина с GPU и ≥ 200 кейсов; рецепт — `docs/04_TRAINING.md`);
- inference-сервиса ассистента (подключается к `context_builder.build_context`).
