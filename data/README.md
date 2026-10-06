# data/ — только реальные данные

**Правило проекта: обучаемся на реальных данных.** В `data/` не должно быть ничего
сгенерированного: ни синтетических сетей, ни демо-разметки, ни тестовых выгрузок.
Всё, что нужно для проверки кода, лежит в `tests/fixtures/`.

## Что где лежит

```
data/
├── raw/                  ИСХОДНЫЕ реальные сети (.inp) — эталон, правится вручную
├── scenarios/            расчёты (создаются по вашим сетям; формат data/scenarios/<id>/)
├── cases/
│   ├── pending/          кейсы ДО разметки (если размечаете внутри команды)
│   ├── inbox/            входящие выгрузки инженеров (сюда кладут JSON из HTML-формы)
│   ├── filled/           РАЗМЕЧЕННЫЕ кейсы — основа датасета
├── batches/              партии и назначения (assignments.json)
├── engineer_forms/       Excel-формы для инженеров (генерируются tools/make_excel_form.py)
├── screen_labels/        реальные скриншоты интерфейса + их разметка (бенчмарк зрения)
│   └── screenshots/
├── collected/            то, что забрали с сервиса разметки (tools/pull_collected.py)
│   ├── cases/            кейсы в формате датасета
│   ├── models/           исходные и очищенные модели инженеров
│   └── contexts/         контексты расчёта для модели (llm_context_*.json)
├── splits/               датасеты обучения: train/val/test/structured/eval_test.jsonl
└── eval/                 отчёты: валидация, качество, метрики модели и зрения
```

Каталоги пустые — так и должно быть: они наполняются реальной работой.
Пустые папки держатся файлами `.gitkeep`.

## Два пути наполнения

**1. Сервис разметки (основной, для внешних инженеров)** — `docs/10_COLLECTION_SERVICE.md`

```bash
# инженер загружает свою модель и размечает её на сайте
python tools/pull_collected.py --url https://ваш-сервис --token <ADMIN_TOKEN> --pipeline
# → data/collected/{cases,models,contexts} → data/splits_collected/
python3 tools/check_data_purity.py          # покажет, что реальное, что синтетическое
```

**2. Внутренняя разметка (свои сети)** — `docs/06_ENGINEER_TASKS.md`

```bash
# положить сети в data/raw/, прописать в src/generate/run_scenarios.py (NETWORKS)
python -m src.generate.run_scenarios --network vn02 --count 20   # расчёты по своей сети
python -m src.generate.build_derived_all                         # KPI, алерты, факты E-xxx
python -m src.dataset.build_cases                                # кейсы → data/cases/pending
python -m src.dataset.make_batches && python -m src.dataset.make_expert_pack --all
# инженеры размечают → data/cases/inbox/ → импорт и приёмка
python -m src.dataset.import_expert_json
python -m src.dataset.validate_cases --dir data/cases/filled
python -m src.dataset.check_quality  --dir data/cases/filled
python -m src.dataset.export_instruct
python -m src.eval.metrics_offline
```

## Проверка, что синтетика не попала в обучение

```bash
python tools/check_data_purity.py
```

Скрипт показывает по каждому каталогу: сколько кейсов реальных, сколько синтетических,
кто и с каким источником их сделал (`annotation.source`, `annotation.annotator_id`).

Защита встроена и в сам экспорт: `export_instruct` **по умолчанию пропускает**
кейсы с источником `pipeline_test` / `synthetic_example` и с логом `pipeline_test`.
Если синтетику нужно включить осознанно (в том числе для будущей аугментации),
есть явный флаг:

```bash
python -m src.dataset.export_instruct --dir data/collected/cases --include-synthetic
```

## Что лежит вне data/

| Путь | Что | Почему не в data/ |
|---|---|---|
| `tests/fixtures/networks/vn01_demo.inp` | демо-сеть для проверки конвейера | это тестовый стенд, а не данные заказчика |
| `tests/fixtures/screen_demo/` | синтетические OCR-блоки и эталоны для метрик зрения | нужны только автотестам |
| `docs/examples/` | 3 образца формата заполненных кейсов | образец формы ответа, помечены `synthetic_example` |

Аугментация (если понадобится) делается отдельным шагом и отдельным каталогом
(`data/augmented/`) с явным флагом при экспорте — чтобы происхождение каждого примера
в датасете всегда было видно.
