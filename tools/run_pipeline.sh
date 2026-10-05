#!/usr/bin/env bash
# Полный конвейер: сеть → сценарии → аналитика → кейсы → партии → формы для инженеров
set -euo pipefail
cd "$(dirname "$0")/.."

NETWORK="${1:-vn01}"
COUNT="${2:-30}"

echo "== 1/5 Сценарии ($NETWORK, $COUNT)" && python -m src.generate.run_scenarios --network "$NETWORK" --count "$COUNT"
echo "== 2/5 Аналитика и контекст"        && python -m src.generate.build_derived_all
echo "== 3/5 Кейсы"                       && python -m src.dataset.build_cases
echo "== 4/5 Партии"                      && python -m src.dataset.make_batches
echo "== 5/5 HTML-формы для инженеров"    && python -m src.dataset.make_expert_pack --all
echo "== Готово. Формы лежат в tools/ExpertCasePack_*.html"
