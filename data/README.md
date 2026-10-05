# Что лежит в data/ и что с этим делать

```
raw/          ИСХОДНЫЕ сети (.inp) — эталон, правится руками, хранится в git
scenarios/    СГЕНЕРИРОВАННЫЕ расчёты (scenario.json, network.inp, results/, derived/)
              воспроизводимы: bash tools/run_pipeline.sh → пересоздаст всё
cases/
  pending/    кейсы ДО разметки (их раздают инженерам)
  inbox/      ВХОДЯЩИЕ выгрузки инженеров (сюда кладут JSON из HTML-формы)
  filled/     РАЗМЕЧЕННЫЕ кейсы (после import_expert_json.py)
  examples/   3 эталонных примера качества разметки (образец для инженеров)
batches/      партии и назначения (assignments.json — кто какие сценарии размечает)
engineer_forms/  Excel-формы (альтернатива HTML)
splits/       датасеты обучения: train/val/test/structured/eval_test .jsonl
eval/         отчёты качества: validation_report, quality_report, model_scores, predictions
```

## ВАЖНО: тестовые данные ≠ обучающие

В `cases/filled/` и `splits/` сейчас лежат данные автотеста конвейера
(`annotator_id = pipeline_test`). Они созданы скриптом `tools/simulate_expert_export.py`
и нужны только чтобы проверить формат и импорт.

**Перед реальным обучением:**

```bash
rm -rf data/cases/filled/* data/cases/inbox/imported/* data/splits/*
# затем работа с инженерами по docs/06_ENGINEER_TASKS.md:
#   инженер открывает tools/ExpertCasePack_<партия>.html
#   заполняет → «Экспорт JSON сценария» → файл в data/cases/inbox/
python -m src.dataset.import_expert_json
python -m src.dataset.validate_cases --dir data/cases/filled
python -m src.dataset.check_quality     --dir data/cases/filled
python -m src.dataset.export_instruct
python -m src.eval.metrics_offline
```
