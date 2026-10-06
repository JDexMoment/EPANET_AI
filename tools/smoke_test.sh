#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Smoke-тест конвейера на демо-сети. Пишет ВСЁ во временный каталог .verify/
# и удаляет его за собой, поэтому data/ остаётся чистым (только реальные данные).
#
# Запуск:  bash tools/smoke_test.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

WORK=".verify"
COUNT="${1:-4}"
FAIL=0

say() { printf "\n\033[1;36m%s\033[0m\n" "$*"; }
check() {                       # check "описание" файл
  if [ -e "$2" ]; then echo "  ✓ $1"; else echo "  ✗ $1 (нет: $2)"; FAIL=1; fi
}

rm -rf "$WORK"; mkdir -p "$WORK"

say "0/8 · подготовка окружения"
python3 -c "import wntr, yaml, jsonschema" 2>/dev/null && echo "  ✓ зависимости пайплайна на месте" \
  || { echo "  ! установите: pip install -r requirements.txt"; FAIL=1; }
test -f tests/fixtures/networks/vn01_demo.inp && echo "  ✓ демо-сеть tests/fixtures/networks/vn01_demo.inp"

say "1/8 · расчёты демо-сети ($COUNT сценариев + baseline)"
python3 -m src.generate.run_scenarios --network vn01 --count "$COUNT" --out "$WORK/scenarios" >/dev/null
check "манифест расчётов" "$WORK/scenarios/manifest.jsonl"
check "baseline посчитан" "$WORK/scenarios/vn01__baseline/results/pressure.csv"

say "2/8 · аналитика и контексты для LLM"
python3 -m src.generate.build_derived_all --manifest "$WORK/scenarios/manifest.jsonl" \
        --scenarios-dir "$WORK/scenarios" >/dev/null
check "факты E-xxx" "$WORK/scenarios/vn01__baseline/derived/evidence.json"
check "контекст модели" "$WORK/scenarios/vn01__baseline/derived/llm_context_whats_happening.json"

say "3/8 · кейсы"
python3 -m src.dataset.build_cases --manifest "$WORK/scenarios/manifest.jsonl" \
        --scenarios-dir "$WORK/scenarios" --out "$WORK/cases/pending" >/dev/null
check "кейсы собраны" "$(ls "$WORK"/cases/pending/c_*.json 2>/dev/null | head -1)"

say "4/8 · партии и формы для инженеров"
python3 -m src.dataset.make_batches --cases-dir "$WORK/cases/pending" --out-dir "$WORK/batches" >/dev/null
check "партии" "$WORK/batches/assignments.json"
python3 -m src.dataset.make_expert_pack --all --batches-dir "$WORK/batches" \
        --cases-dir "$WORK/cases/pending" --scenarios-dir "$WORK/scenarios" \
        --out-dir "$WORK/forms" >/dev/null
if ls "$WORK"/forms/*.html >/dev/null 2>&1; then echo "  ✓ HTML-форма собрана"; else echo "  ~ формы пропущены (нет партий)"; fi

say "5/8 · имитация выгрузки инженера (синтетика — только для проверки)"
BATCH="$WORK/batches/batch_exp_01_01.json"
EXPORT="$WORK/inbox/batch_exp_01_01__pipeline_test.json"
if [ -f "$BATCH" ]; then
  mkdir -p "$WORK/inbox"
  python3 tools/simulate_expert_export.py --batch "$BATCH" --scenarios-dir "$WORK/scenarios" \
          --out "$EXPORT" >/dev/null 2>&1 || true
  check "выгрузка инженера" "$EXPORT"
else
  echo "  ~ партии нет — шаг пропущен"
fi

say "6/8 · импорт, валидация, качество"
if [ -s "$EXPORT" ]; then
  python3 -m src.dataset.import_expert_json --inbox "$WORK/inbox" \
          --pending "$WORK/cases/pending" --filled "$WORK/cases/filled" >/dev/null
  python3 -m src.dataset.validate_cases --dir "$WORK/cases/filled" \
          --report "$WORK/validation_report.json" | tail -2
  python3 -m src.dataset.check_quality --dir "$WORK/cases/filled" --out "$WORK/quality_report.json" | tail -2
else
  echo "  ~ шаг пропущен (нет выгрузки)"
fi

say "7/8 · экспорт датасета: синтетика должна быть ОТСЕЧЕНА"
OUT=$(python3 -m src.dataset.export_instruct --dir "$WORK/cases/filled" --out "$WORK/splits" 2>&1 | tail -3)
echo "$OUT" | sed 's/^/  /'
if echo "$OUT" | grep -q "отсечено синтетических"; then
  echo "  ✓ защита от синтетики работает ($(echo "$OUT" | grep -o "отсечено синтетических кейсов: [0-9]*"))"
else
  echo "  ~ синтетических кейсов в выгрузке не было"
fi
ROWS=$( { cat "$WORK"/splits/train.jsonl 2>/dev/null || true; } | wc -l )
[ "$ROWS" = "0" ] && echo "  ✓ в датасет обучения не попало ни одного синтетического примера" \
                  || { echo "  ✗ В TRAIN ПОПАЛА СИНТЕТИКА: $ROWS строк"; FAIL=1; }

say "7b/8 · обратная проверка: с флагом --include-synthetic данные выгружаются"
python3 -m src.dataset.export_instruct --dir "$WORK/cases/filled" --out "$WORK/splits_syn" \
        --include-synthetic --include-drafts >/dev/null 2>&1 || true
SYN=$( { cat "$WORK"/splits_syn/train.jsonl "$WORK"/splits_syn/val.jsonl "$WORK"/splits_syn/test.jsonl 2>/dev/null || true; } | wc -l )
if [ "$SYN" -gt 0 ]; then echo "  ✓ с явным флагом выгружено строк: $SYN (примеры формата пригодны для отладки)";
else echo "  ~ нечего выгружать (кейсы не заполнены)"; fi

say "8/8 · подсистема понимания экрана (синтетические фикстуры)"
python3 -m src.eval.metrics_screen --labels tests/fixtures/screen_demo \
        --pred tests/fixtures/screen_demo/predictions.jsonl --out "$WORK/screen_scores.json" \
  | { grep -E "OK|НЕТ" || true; } | sed 's/^/  /'

say "уборка"
rm -rf "$WORK"
echo "  временный каталог $WORK удалён"

if [ "$FAIL" = "0" ]; then
  printf "\n\033[1;32mSMOKE-ТЕСТ ПРОЙДЕН\033[0m · data/ осталась чистой:\n"
  python3 tools/check_data_purity.py | tail -4
  exit 0
else
  printf "\n\033[1;31mЕСТЬ ОШИБКИ — см. ✗ выше\033[0m\n"
  exit 1
fi
