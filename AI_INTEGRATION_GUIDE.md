# Гайд по интеграции AI в EPANET 2.2 (Delphi + Python + Qwen3)

Пошаговая инструкция: как настроить рабочее место, что где лежит, как собирать и запускать.

---

## ШАГ 0. Подготовка рабочего места

### VS Code
```bash
git clone https://github.com/JDexMoment/EPANET_AI.git
cd EPANET_AI
code .
```
Рекомендуемые расширения VS Code:
- **Python** (Microsoft) + **Pylance**
- **Ruff** или **Flake8**
- **Delphi / Pascal** (Tomaţia-Vlad Pascal, если редактируете `.pas`)
- **Jupyter** — для разведочного анализа результатов
- **Markdown All in One**

### Delphi (только Windows)
- Embarcadero Delphi 10.x/11/12 (Community Edition подходит)
- Steema TeeChart (для графиков) — по инструкции из `Delphi_GUI/Readme_GUI.txt`
- Сначала **Install** пакета `Delphi_GUI/components/Epa.dpk`

---

## ШАГ 1. Структура репозитория (что добавлено под AI)

```
EPANET_AI/
├── Delphi_GUI/epanet2w/
│   ├── Fmain.pas             ← ИЗМЕНЁН: кнопка «AI» + меню «AI Ассистент»
│   ├── Fmap.pas              ← ИЗМЕНЁН: ПКМ по карте → AI
│   ├── Epanet2w.dpr          ← ИЗМЕНЁН: подключены Uai_bridge, Fai_assistant
│   ├── Uai_bridge.pas        ← НОВЫЙ: сбор контекста экрана + HTTP к Python
│   ├── Uai_bridge.dfm        ← НОВЫЙ (не требуется — компоненты создаются в коде)
│   ├── Fai_assistant.pas     ← НОВЫЙ: окно ассистента
│   └── Fai_assistant.dfm     ← НОВЫЙ: форма окна
├── SRC_engines/              ← без изменений (C-движок EPANET 2.2)
├── CMakeLists.txt            ← НОВЫЙ: сборка движка через CMake (опционально)
├── ai_module/                ← НОВЫЙ: весь Python AI/аналитический слой
│   ├── README.md             ← ПОЛНАЯ документация (читать обязательно)
│   ├── requirements.txt
│   ├── run_service.py
│   ├── config/
│   │   ├── settings.py       ← пороги, пути, выбор LLM-бэкенда
│   │   └── rules_and_norms.json ← нормы, причины, рекомендации
│   ├── engine_adapter/ctypes_epanet.py
│   ├── analytics/            ← детерминированные KPI, алерты, сравнение сценариев
│   ├── context/              ← схемы JSON + Context Builder
│   ├── knowledge_rag/        ← RAG-слой нормативов
│   ├── llm/                  ← Qwen3 клиент + промпты
│   ├── reports/              ← генератор отчётов MD/HTML
│   ├── api/                  ← FastAPI сервис
│   ├── training/             ← датасет, валидация, QLoRA, бенчмарк
│   ├── tests/                ← 29 тестов
│   └── data/
│       ├── raw_networks/     ← СЮДА кладём .INP
│       ├── scenarios/        ← генерируется
│       ├── sft_datasets/     ← генерируется
│       └── benchmarks/       ← генерируется
└── start_ai_service.bat      ← запуск Python-сервиса на Windows
```

---

## ШАГ 2. Сборка C-движка EPANET (для Python)

**Linux / macOS (автоматически при первом запуске):**
```bash
cd EPANET_AI/SRC_engines
gcc -O2 -fPIC -shared *.c -lm -o libepanet2.so
```
*(исключая `main.c`, если нужна только DLL)*

**Windows (MSYS2/MinGW):**
```bash
gcc -O2 -shared -o epanet2.dll epanet.c epanet2.c genmmd.c hash.c hydcoeffs.c ^
  hydraul.c hydsolver.c hydstatus.c inpfile.c input1.c input2.c input3.c ^
  mempool.c output.c project.c quality.c qualreact.c qualroute.c report.c ^
  rules.c smatrix.c -lm
```

**Windows (MSVC / Visual Studio):**
```
cl /LD /Fe:epanet2.dll epanet.c epanet2.c genmmd.c hash.c hydcoeffs.c hydraul.c ^
   hydsolver.c hydstatus.c inpfile.c input1.c input2.c input3.c mempool.c ^
   output.c project.c quality.c qualreact.c qualroute.c report.c rules.c smatrix.c
```

**Альтернатива:** взять готовый `epanet2.dll` из официального дистрибутива EPANET 2.2
и передать путь явно:
```python
from ai_module.engine_adapter.ctypes_epanet import EpanetEngineAdapter
EpanetEngineAdapter(lib_path=r"C:\Program Files\EPANET\epanet2.dll")
```

---

## ШАГ 3. Запуск Python AI-сервиса

```bash
cd EPANET_AI
python -m venv .venv && .venv\Scripts\activate
pip install -r ai_module/requirements.txt
python -m ai_module.run_service
```
Сервис слушает `http://127.0.0.1:8765`. Проверка:
```bash
curl http://127.0.0.1:8765/api/v1/health
curl http://127.0.0.1:8765/docs        # Swagger UI
```

---

## ШАГ 4. Сборка Delphi GUI

1. `Delphi_GUI/components/Epa.dpk` → **Install**
2. `Delphi_GUI/epanet2w/Epanet2w.dproj` → **Build**
3. Скопировать `epanet2.dll` рядом с `epanet2w.exe`
4. Запустить, открыть `.INP`, **Project → Run Analysis**
5. Нажать **«AI»** на панели инструментов (или меню **AI Ассистент**)

### Что происходит в момент нажатия
`Uai_bridge.BuildUIContextJSON` собирает:
- `selection` — выбранный объект из Browser/Property Editor
- `viewport` — реальные границы zoom-окна + ID узлов/труб, попадающих на экран
- `simulation_state` — текущий период времени, `Nperiods`, флаг успешного расчёта
- экспорт сети в `%TEMP%\epanet_ai_snapshot.inp`
- скриншот карты в `%TEMP%\epanet_ai_viewport.bmp`

и POST-ит это в `/api/v1/analyze`.

### Если нужно поменять адрес/порт сервиса
В `Uai_bridge.pas`:
```pascal
const
  AI_SERVICE_DEFAULT_URL = 'http://127.0.0.1:8765';
```

---

## ШАГ 5. Подключение Qwen3

```bash
ollama pull qwen3:8b
set EPANET_AI_BACKEND=ollama
set EPANET_AI_OLLAMA_MODEL=qwen3:8b
python -m ai_module.run_service
```
Перезапустите сервис — при следующем клике по «AI» ответы будет генерировать Qwen3.
Если Ollama недоступен, сервис автоматически переключится на детерминированный синтезатор
(ответ будет корректным, но без «языкового» разнообразия).

---

## ШАГ 6. Подготовка данных для дообучения

1. Положите `.INP` в `ai_module/data/raw_networks/`
2. `python -m ai_module.training.generate_dataset --max-periods 6`
3. `python -m ai_module.training.validate_dataset` → должно быть `PASSED`
4. `python -m ai_module.training.benchmark --backend deterministic_pilot`

Подробные форматы JSON — в `ai_module/README.md` §4.

---

## ШАГ 7. Дообучение и приёмка

```bash
python -m ai_module.training.train_qlora --base-model Qwen/Qwen3-8B --epochs 3
set EPANET_AI_BACKEND=hf_local
set EPANET_AI_LORA_PATH=ai_module/training/checkpoints/qwen3-epanet-lora
python -m ai_module.run_service
python -m ai_module.training.benchmark --backend hf_local --model-name Qwen3-8B+LoRA
```

---

## ШАГ 8. Контроль качества перед коммитом

```bash
python -m pytest ai_module/tests -q
python -m ai_module.training.validate_dataset
python -m ai_module.training.benchmark --backend deterministic_pilot
```

Все три команды должны завершаться успешно.
