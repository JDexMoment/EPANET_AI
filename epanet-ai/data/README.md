# data/ — только реальные данные

**Правило проекта: обучаемся на реальных данных.** В `data/` не должно быть ничего
сгенерированного: ни синтетических картинок, ни демо-ответов, ни тестовых выгрузок.
Всё, что нужно для проверки кода, лежит в `tests/fixtures/`.

## Структура

```
data/
├── README.md
└── screens/                  ДАТАСЕТ ЗАКАЗЧИКА: «скриншот AquaBit → ответ» (главный трек)
    ├── raw/                  сюда кладут присланное как есть (картинки + ответы)
    ├── images/               рабочие копии картинок (приводятся к нужному размеру)
    ├── ocr/                  текст, «видимый» на экране (если заказчик приложил)
    ├── pairs_template.csv    шаблон таблицы пар (колонки и примеры)
    ├── manifest.jsonl        пары: картинка, вопрос, ответ, группа, отпечатки   ← create
    ├── qa_report.json        отчёт контроля качества (дубли, отказы, спорные числа) ← create
    └── {train,val,test}.jsonl, swift_*.jsonl, sharegpt_*.jsonl, eval_reference.jsonl ← create
```

`raw/`, `images/`, `ocr/` и `*.jsonl` держатся вне git (см. `.gitignore`) — данные заказчика
в репозиторий не коммитим. Пустые папки сохраняются файлами `.gitkeep`.

## Порядок работы (одна цепочка)

```bash
# 0) в data/screens/raw/ — скриншоты; ответы Gemini либо рядом (.txt с тем же именем),
#    либо в файле pairs.csv (шаблон — pairs_template.csv), либо в export.jsonl
python tools/prepare_pairs_worksheet.py --shots data/screens/raw --out data/screens/ds   # заготовка

# 1) импорт пар → манифест
python -m src.dataset.import_screenshots --src data/screens/ds --summary

# 2) контроль качества: дубли кадров, пустые/битые ответы, числа вне экрана
python -m src.dataset.check_screenshot_pairs --manifest data/screens/ds/manifest.jsonl

# 3) сборка датасета обучения (сплиты по группам, форматы swift/sharegpt)
python -m src.dataset.build_vl_dataset --manifest data/screens/ds/manifest.jsonl --out data/screens/vl

# 4) план обучения под конкретную машину
python -m src.train.vl_lora --data data/screens/vl --print-plan
```

Поддерживаемые раскладки присланного (сшивка картинок и ответов) описаны в шапке
`src/dataset/import_screenshots.py`: файл-выгрузка (jsonl/json/csv), ответы файлами
`answers/<имя>.txt`, ответ рядом с картинкой, OCR-папка.

## Материалы вне data/ (в репозиторий не коммитятся)

| Что | Где держать | Зачем |
|---|---|---|
| `.inp`-экспорты AquaBit | рядом с датасетом (вне git) | проверка чисел: `tools/aquabit_inp.py`, `tools/extract_claims.py` |
| Отчёты (PDF) | отдельная папка | справочник терминологии, таблицы для сверки, картинки для разметки |
| Результаты расчётов (когда появятся) | отдельная папка | истина по динамике (расходы/давления во времени) |

## Проверка чистоты

```bash
python tools/check_data_purity.py     # синтетика в data/ + утечка фикстур в датасет (dHash)
bash tools/smoke_test.sh              # весь трек на фикстурах, пишет в .verify/ и убирает за собой
```
