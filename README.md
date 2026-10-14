# EPANET AI-модуль: локальный помощник «скриншот AquaBit → ответ»

Обучаем компактную локальную модель-зрение (VLM), которая смотрит на скриншот программы
**AquaBit** (гидравлические расчёты сетей водоснабжения, форк EPANET) и по-русски объясняет,
что там происходит: что за объект, что показывают числа, на что обратить внимание.
Эталон ответов — разборы, которые заказчик получил от Gemini. Всё работает офлайн, на ПК клиента.

```
скриншот AquaBit ──▶ препроцессинг ──▶ VLM (Qwen3-VL + LoRA, 4-бит) ──▶ текст ответа
                                             ▲
        датасет: скриншоты + ответы Gemini ───┘
        (проверка чисел по модели .inp — отдельным слоем, docs/14 §4)
```

**Разобраться, как всё связано:** `docs/14_PIPELINE_AND_INTEGRATION.md` — пайплайн данных
и модели, роль `.inp`, варианты интеграции с AquaBit.
**Что делать руками (сбор данных):** `docs/15_AQUABIT_DATA_HOWTO.md`.

## Быстрый старт

```bash
pip install -r requirements.txt

# — собрать датасет из присланного (скриншоты + ответы Gemini)
python tools/prepare_pairs_worksheet.py --shots data/screens/raw --out data/screens/ds  # заготовка листа
python -m src.dataset.import_screenshots --src data/screens/ds --summary
python -m src.dataset.check_screenshot_pairs --manifest data/screens/ds/manifest.jsonl
python -m src.dataset.build_vl_dataset   --manifest data/screens/ds/manifest.jsonl --out data/screens/vl

# — посмотреть план обучения под конкретную машину (обучение запускается на GPU-машине)
python -m src.train.vl_lora --data data/screens/vl --print-plan
python -m src.train.vl_lora --data data/screens/vl --emit-script outputs/train_vl.sh

# — метрики: насколько ответы «как эталон»
python -m src.eval.metrics_vl --ref data/screens/vl/dataset.jsonl --pred ours=pred.jsonl

# — утилита модели сети (.inp от AquaBit): сводка, поиск, проверка чисел, конвертация
python tools/aquabit_inp.py stats --inp "модель для ИИ — копия.txt"
python tools/aquabit_inp.py link  --inp "модель для ИИ — копия.txt" --id 3459843 --q 87.9
python tools/aquabit_inp.py convert --inp "модель для ИИ — копия.txt" --out model_epanet.inp

# — прототип приложения: скриншот-контекст + модель → карточка объекта с графиком
python tools/assistant_prototype.py --model "модель для ИИ — копия.txt" --screen ответ.txt --out outputs/assistant

# — вытащить проверяемые утверждения из ответов и сверить с моделью
python tools/extract_claims.py --answers data/screens/ds/export.jsonl --inp "модель для ИИ — копия.txt" --out claims.csv

# — проверить, что в датасете нет синтетики, и прогнать автотесты трека
python tools/check_data_purity.py
bash tools/smoke_test.sh
```

## Структура

| Каталог | Что там |
|---|---|
| `src/dataset/` | импорт пар «скриншот+ответ», контроль качества, сборка сплитов |
| `src/model_io/` | чтение моделей `.inp` / `.NET` / `.epanet` в единый вид (для приложения) |
| `src/vision/preprocess.py` | препроцессинг картинок, dHash, размеры |
| `src/train/vl_lora.py` | план и скрипты обучения Qwen3-VL (LoRA/QLoRA) |
| `src/eval/metrics_vl.py` | метрики ответов (числа, ID, смысл, grounding, отказы) |
| `configs/vision.yaml` | все настройки трека: вопрос, пороги, сплиты, модель |
| `tools/` | рабочие утилиты: `.inp` AquaBit, извлечение утверждений, лист пар, **прототип приложения**, дымовой тест |
| `data/screens/` | место датасета заказчика (в репозитории — только структура и шаблон) |
| `tests/fixtures/` | синтетические фикстуры для автотестов (в датасет не попадают) |
| `docs/` | документация (см. ниже) |
| `archive/` | **отменённые треки** прошлых постановок; в работе не участвуют (`archive/README.md`) |

## Документация

| Файл | О чём |
|---|---|
| `docs/16_ASSISTANT_APP.md` | **приложение-ассистент**: архитектура (VLM + модель + расчёты + отчёты), план разработки, что даёт рост датасета |
| `docs/14_PIPELINE_AND_INTEGRATION.md` | **как всё устроено**: пайплайн данных и модели, роль `.inp`, интеграция с AquaBit, словарь |
| `docs/15_AQUABIT_DATA_HOWTO.md` | **как собирать данные**: таблица пар, экспорт из AquaBit, отчёты, разметка, чек-лист |
| `docs/12_SCREENSHOT_FINETUNE.md` | обучение: почему без отдельной CV-модели, датасет, шаги, метрики, риски |
| `docs/13_DATA_AUDIT.md` | аудит присланного от заказчика (Семей): что годно, что запрошено ещё |
| `docs/09_MODELS_AND_DEPLOYMENT.md` | модель и железо клиента: варианты, квантование, сборка GGUF |
| `docs/01_PROJECT_STRUCTURE.md` | структура проекта и разделение ответственности |

## Данные: правило чистоты

**Обучаемся только на реальных данных** — скриншотах и ответах заказчика (Gemini/инженер).
Синтетика допустима лишь в `tests/fixtures/`. Проверка: `python tools/check_data_purity.py`
(она же ловит утечку фикстур в датасет по dHash). Демо для автотестов воспроизводится
`python tools/make_demo_screens.py --out .verify/screens` и никогда не попадает в `data/`.

## Чего пока нет (следующие шаги)

- **большого датасета**: сейчас 24 пары «Семей» — затравка; цель 300–500+ разных экранов
  и проектов (`docs/15`, §8);
- обученной модели: нужна GPU-машина (аренда) — этапы ④–⑥ из `docs/14`, §3;
- выгрузки результатов расчёта из AquaBit (запрос вендору — `docs/15`, §3.3).
