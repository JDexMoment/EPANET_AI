# Конвейер: от сети до датасета обучения

## Быстрый цикл (всё одной командой)

```bash
bash tools/run_pipeline.sh              # пересбор: сценарии → кейсы → партии → формы
```

> В репозитории нет сгенерированных данных — `data/` пуста и наполняется реальной работой
> (`data/README.md`). Команды ниже запускаются, когда у вас есть **свои** сети (в `data/raw/`,
> прописаны в `NETWORKS`) — либо для проверки кода на демо-сети из `tests/fixtures/`.

## Пошагово и что получается на выходе

| Шаг | Команда | Результат |
|---|---|---|
| 1. Сценарии | `python -m src.generate.run_scenarios --network vn01 --count 30` | `data/scenarios/<id>/{scenario.json, network.inp, results/*.csv}` + `manifest.jsonl` |
| 2. Аналитика и контекст | `python -m src.generate.build_derived_all` | `derived/derived_metrics.json`, `derived/evidence.json`, `derived/llm_context_*.json` |
| 3. Кейсы | `python -m src.dataset.build_cases` | `data/cases/pending/c_<scenario>__<mode>__NN.json` |
| 4. Партии | `python -m src.dataset.make_batches` | `data/batches/batch_exp_*.json`, `assignments.json` |
| 5. Формы для инженеров | `python -m src.dataset.make_expert_pack --all` | `tools/ExpertCasePack_<партия>.html` |
| 6. Работа инженеров | — | выгрузки JSON в `data/cases/inbox/` |
| 7. Импорт | `python -m src.dataset.import_expert_json` | `data/cases/filled/` (+ автоматические ask-кейсы) |
| 8. Валидация | `python -m src.dataset.validate_cases --dir data/cases/filled` | `data/eval/validation_report.json` |
| 9. Качество/IQA | `python -m src.dataset.check_quality --dir data/cases/filled` | `data/eval/quality_report.json` |
| 10. Экспорт датасета | `python -m src.dataset.export_instruct` | `data/splits/{train,val,test,structured,eval_test}.jsonl` |
| 11. Оценка датасета | `python -m src.eval.metrics_offline` | консольный отчёт + вердикт по объёму |
| 12. Бенчмарк модели | `python -m src.eval.metrics_model --pred data/eval/predictions.jsonl` | `data/eval/model_scores.json` |

## Ветка «данные с сайта разметки»

Если гидравлики размечают на сервисе (`docs/10_COLLECTION_SERVICE.md`):

```bash
python tools/pull_collected.py --url https://epanet.example.com --token <ADMIN_TOKEN> --pipeline
# → data/collected/cases → data/splits_collected/{train,val,test,structured,eval_test}.jsonl
```

Эти кейсы помечены `annotation.source = "collection_service"` и попадают в датасет наравне
с разметкой внутренних сценариев.

## Проверка конвейера без инженеров (автотест)

```bash
python tools/simulate_expert_export.py --batch data/batches/batch_exp_01_01.json
python -m src.dataset.import_expert_json
python -m src.dataset.validate_cases --dir data/cases/filled
python -m src.dataset.export_instruct
python -m src.eval.metrics_offline
```

Эти данные помечены `expert_id = pipeline_test` — для обучения они **не годятся** и
отсекаются автоматически (`export_instruct` пропускает источник `pipeline_test`).
Нужны только чтобы убедиться, что формат, импорт и экспорт работают. После проверки удалите:

```bash
rm -rf data/cases/filled/* data/cases/inbox/* data/splits/*
python tools/check_data_purity.py     # должно показать: синтетики нет
```

## Работа с отдельным сценарием (отладка)

```bash
# посмотреть контекст, который увидит модель, по конкретному объекту
python -m src.context_builder data/scenarios/vn01__baseline --mode explain_object --object J-105

# пересчитать аналитику только по одному сценарию
python -m src.generate.build_derived_all --only vn01__baseline
```

## Контроль происхождения данных

```bash
python tools/check_data_purity.py                       # все рабочие каталоги
python tools/check_data_purity.py --dir data/cases/filled
```

## Частые проблемы

| Симптом | Причина / решение |
|---|---|
| `ОШИБКА ... 'value'` в context_builder | у правила в `thresholds.yaml` нет поля `value` → использовать `r.get('value','')` |
| Кейсы собраны, но фактов нет | сначала `build_derived_all`, потом `build_cases` |
| В партии меньше сценариев, чем ожидалось | партии формируются по `configs/experts.yaml → load.scenarios_per_batch` |
| Инженер прислал файл, но кейсы не заполнились | имена кейсов в выгрузке и в `pending/` должны совпадать; файл после импорта уезжает в `inbox/imported/` |
| Числа в отчёте не проходят валидацию | число отсутствует в evidence → либо добавить факт в аналитику, либо исправить ответ |

## Регламент версий

- `configs/`, `schemas/`, `src/` — в git.
- `data/scenarios/`, `data/cases/pending/` — воспроизводимы, в git не обязательны.
- `data/cases/filled/`, `data/splits/`, `data/eval/` — хранить с датой и версией
  (например, `splits_v2026-10-05/`), потому что это «прошивка» обучения.
