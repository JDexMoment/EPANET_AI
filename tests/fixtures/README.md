# Синтетические фикстуры (для автотестов, НЕ для обучения)

Здесь лежит всё, что сгенерировано для проверки кода. Эти файлы **не являются данными**
и никогда не должны попадать в `data/` (это стережёт `tools/check_data_purity.py` —
он ловит такие утечки в том числе по отпечатку картинок, dHash).

| Что | Зачем |
|---|---|
| `networks/aquabit_demo.inp` | учебная сеть «как экспортирует AquaBit»: статусы труб на месте minor loss (`Closed`, `Open`, `CV`), хвостовые комментарии `;`, кастомная секция `[PRESS]`, кастомные опции. Проверяет `tools/aquabit_inp.py` (stats / link / convert) |
| `screens_pairs/` | 6 демо-пар «скриншот + ответ» в раскладке `images/` + `answers/` + `ocr/` — прогоняют весь трек: импорт → QA → сборка сплитов → метрики |

## Как это гоняется

```bash
bash tools/smoke_test.sh          # весь трек на этих фикстурах (5 шагов), пишет в .verify/
```

Отдельные проверки:

```bash
python tools/aquabit_inp.py stats --inp tests/fixtures/networks/aquabit_demo.inp
python tools/aquabit_inp.py link --inp tests/fixtures/networks/aquabit_demo.inp --id P-1 --q 87.9
python tools/aquabit_inp.py convert --inp tests/fixtures/networks/aquabit_demo.inp --out /tmp/aq.inp
python -m src.dataset.import_screenshots --src tests/fixtures/screens_pairs --out /tmp/mod.jsonl
```

Демо-датасет для тестов воспроизводится командой
`python tools/make_demo_screens.py --out .verify/screens` (и всегда — во временный каталог).
