#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Smoke-тест главного трека: «скриншоты → ответ» + утилита AquaBit-.inp.
# Пишет ВСЁ во временный каталог .verify/ и удаляет его за собой,
# поэтому data/ остаётся чистой (в датасете — только реальные данные заказчика).
#
# Запуск:  bash tools/smoke_test.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

WORK=".verify"
FAIL=0

say() { printf "\n\033[1;36m%s\033[0m\n" "$*"; }
check() {                       # check "описание" файл
  if [ -e "$2" ]; then echo "  ✓ $1"; else echo "  ✗ $1 (нет: $2)"; FAIL=1; fi
}

rm -rf "$WORK"; mkdir -p "$WORK"

say "0/6 · подготовка окружения"
python3 -c "import PIL, yaml" 2>/dev/null && echo "  ✓ зависимости на месте (pillow, pyyaml)" \
  || { echo "  ! установите: pip install -r requirements.txt"; FAIL=1; }
test -f tests/fixtures/networks/aquabit_demo.inp && echo "  ✓ фикстура формата AquaBit-.inp"
test -d tests/fixtures/screens_pairs/images && echo "  ✓ фикстура пар «скриншот + ответ»"

say "1/6 · конвейер трека: демо-скриншоты → импорт → QA → сборка → план обучения"
python3 tools/make_demo_screens.py --out "$WORK/screens" >/dev/null
python3 -m src.dataset.import_screenshots --src "$WORK/screens" \
        --out "$WORK/screens/manifest.jsonl" | grep -E "скриншотов|с ответом|групп" | sed 's/^/  /'
python3 -m src.dataset.check_screenshot_pairs --manifest "$WORK/screens/manifest.jsonl" \
        | grep -E "чистых|блокирующих|кластеров|групп для" | sed 's/^/  /'
python3 -m src.dataset.build_vl_dataset --manifest "$WORK/screens/manifest.jsonl" \
        --out "$WORK/screens/ds" | grep -E "взято|train |каталог" | sed 's/^/  /'
python3 -m src.train.vl_lora --data "$WORK/screens/ds" | grep -E "базовая модель|шагов|видеопамять" | sed 's/^/  /'

say "2/6 · метрики: «ответ как эталон» проходит пороги"
WORK="$WORK" python3 - <<'PYEOF'
import json, os, pathlib
work = pathlib.Path(os.environ["WORK"])
rows = [json.loads(l) for l in (work / "screens/ds/dataset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out = work / "screens/pred_ours.jsonl"
out.write_text("\n".join(json.dumps({"id": r["id"], "answer": r["answer"]}, ensure_ascii=False) for r in rows), encoding="utf-8")
print("  подготовлено предсказаний:", len(rows))
PYEOF
python3 -m src.eval.metrics_vl --ref "$WORK/screens/ds/dataset.jsonl" \
        --pred ours="$WORK/screens/pred_ours.jsonl" --out "$WORK/screens/vl_metrics.json" \
  | grep -E "набор|ours|пороги пройдены" | sed 's/^/  /'

say "3/6 · утилита AquaBit-.inp (синтетическая фикстура формата заказчика)"
python3 tools/aquabit_inp.py stats --inp tests/fixtures/networks/aquabit_demo.inp \
  | grep -E "кастом AquaBit|труб с явным" | sed 's/^/  /'
python3 tools/aquabit_inp.py link --inp tests/fixtures/networks/aquabit_demo.inp --id P-1 --q 87.9 \
  | grep -E "ТРУБА|при Q" | sed 's/^/  /'
python3 tools/aquabit_inp.py convert --inp tests/fixtures/networks/aquabit_demo.inp \
  --out "$WORK/aquabit_flat.inp" | grep -E "выпрямлено|вырезано" | sed 's/^/  /'
if grep -q "\[PRESS\]" "$WORK/aquabit_flat.inp"; then
  echo "  ✗ кастомная секция [PRESS] не вырезана"; FAIL=1
else
  echo "  ✓ [PRESS] и кастомные опции удалены"
fi
if python3 -c "import wntr" 2>/dev/null; then
  WORK="$WORK" python3 - <<'PYEOF' | sed 's/^/  /'
import os
work = os.path.abspath(os.environ["WORK"])
os.chdir(work)                        # temp-файлы WNTR не должны пачкать репозиторий
import wntr
wn = wntr.network.WaterNetworkModel(os.path.join(work, "aquabit_flat.inp"))
print(f"✓ WNTR прочитал сконвертированный .inp: узлов {wn.num_nodes}, участков {wn.num_links}")
PYEOF
else
  echo "  · WNTR не установлен — проверка чтения пропущена (необязательно)"
fi

say "4/6 · чтение моделей (.inp/.NET/.epanet) и прототип карточки"
python3 - <<'PYEOF' | sed 's/^/  /'
import sys
sys.path.insert(0, ".")
from src import model_io
m = model_io.read_model("tests/fixtures/networks/aquabit_demo.inp")
print(f"✓ model_io прочитал фикстуру: формат {m.fmt}, труб {m.count('PIPES')}, узлов {m.count('JUNCTIONS')}")
PYEOF
mkdir -p "$WORK/assistant"
python3 tools/assistant_prototype.py --model tests/fixtures/networks/aquabit_demo.inp \
        --objects P-1 --q 87.9 --out "$WORK/assistant" \
  | grep -E "model_io|прочитал|труба|V=" | sed 's/^/  /' || true
check "карточка объекта собрана" "$WORK/assistant/card.html"
check "контекст для VLM собран" "$WORK/assistant/context_for_vlm.txt"

say "5/6 · чистота данных: в датасет не попала синтетика"
python3 tools/check_data_purity.py || FAIL=1

say "6/6 · уборка"
rm -rf "$WORK"
echo "  временный каталог $WORK удалён"

if [ "$FAIL" = "0" ]; then
  printf "\n\033[1;32mSMOKE-ТЕСТ ПРОЙДЕН\033[0m · data/ осталась чистой\n"
  exit 0
else
  printf "\n\033[1;31mЕСТЬ ОШИБКИ — см. ✗ выше\033[0m\n"
  exit 1
fi
