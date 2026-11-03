# EPANET-AI (`epanet-ai` / `aquabit-ai`)

ИИ-модуль валидации, очистки нулевых строк, профилирования экспорта и интерпретации гидравлических расчётов для ПК **AquaBit / EPANET-AI**.

Поддерживает **3 формата входных данных**:
1. **Папки городов (`data\<город>\*.csv`, 13 CSV с широкими матрицами `R0..R1439`, ADR-0007 / ADR-0008)**;
2. **Целевой архив `export.zip` (§2)** с `manifest.json`;
3. **Многосекционные legacy CSV-выгрузки (`cp1251` / `\t`, ADR-0006)**.

---

## Быстрый старт и команды для Windows PowerShell (проект `EPANET-AI`)

Откройте **PowerShell** в папке вашего проекта `EPANET-AI` (где лежат `pyproject.toml`, папка `src` и ваша папка `data`):

### Шаг 0. Однократная настройка окружения в PowerShell

```powershell
# Включаем UTF-8 в текущей сессии PowerShell для корректного вывода кириллицы
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

# Создаём виртуальное окружение (если ещё не создано) и ставим пакет EPANET-AI в editable-режиме
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

> **Почему раньше не запускалась команда `aquabit-ai` в PowerShell?**
> В Windows PowerShell исполняемые скрипты лежат внутри `.\.venv\Scripts\` (которой нет в `PATH`, если окружение не активировано или заблокировано политикой `ExecutionPolicy`).
> Поэтому в PowerShell надёжнее всего вызывать либо `.\.venv\Scripts\epanet-ai.exe`, либо `.\.venv\Scripts\python.exe -m epanet_ai` (работает всегда, даже при запрете `.ps1`-скриптов!).

---

### Команды запуска в PowerShell (через `python -m epanet_ai`)

```powershell
# 1. Только проверка всех городов внутри .\data на нулевые значения (исходные CSV НЕ меняются):
.\.venv\Scripts\python.exe -m epanet_ai check-zeros ".\data" --out ".\artifacts\zero_audit"

# 2. Удаление нулевых строк в 4 таблицах (Поток Насос, Потребители Узел, Потребление Узел, Узел)
#    с сохранением результата в отдельную папку .\data_cleaned:
.\.venv\Scripts\python.exe -m epanet_ai clean-zeros ".\data" --out ".\data_cleaned" --report-dir ".\artifacts\zero_clean_report"

# 3. Удаление нулевых строк НА МЕСТЕ (перезапись исходных CSV внутри .\data):
.\.venv\Scripts\python.exe -m epanet_ai clean-zeros ".\data" --in-place --report-dir ".\artifacts\zero_clean_report"

# 4. Открыть готовый HTML-отчёт в браузере по умолчанию прямо из PowerShell:
Invoke-Item ".\artifacts\zero_clean_report\zero_audit_report.html"

# 5. Профилирование информативности и избыточности R0..R1439 по всей папке .\data:
.\.venv\Scripts\python.exe -m epanet_ai profile-export ".\data" --out ".\artifacts\export_profile"
Invoke-Item ".\artifacts\export_profile\export_optimization_report.html"

# 6. Пакетная строгая валидация всех городов внутри .\data:
.\.venv\Scripts\python.exe -m epanet_ai batch-validate ".\data" --out ".\artifacts\batch_validation"

# 7. Валидация и препроцессинг одного города (например, «тенино») в сжатый Zstd Parquet:
.\.venv\Scripts\python.exe -m epanet_ai validate ".\data\тенино" --out ".\artifacts\tenino_val"
.\.venv\Scripts\python.exe -m epanet_ai preprocess ".\data\тенино" --allow-broken-topology --out ".\artifacts\tenino_parquet"

# 8. Запуск всех автотестов проекта:
.\.venv\Scripts\python.exe -m pytest
```

### Вариант запуска вообще без установки пакета (если установлены библиотеки `pandas`, `pyarrow`, `typer`, `pydantic`, `pyyaml`, `jinja2`, `jsonschema`):

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:PYTHONUTF8 = "1"
python -m epanet_ai clean-zeros ".\data" --out ".\data_cleaned" --report-dir ".\artifacts\zero_clean_report"
```
