#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Запуск сервиса сбора разметки на Linux / macOS (для Windows — tools/run_service.ps1).
#
#   bash tools/run_service.sh                      # порт 8080, токены генерируются
#   bash tools/run_service.sh --port 9000 --local  # только с этого компьютера
#   bash tools/run_service.sh --admin мой-токен \
#        --experts "gidr01:Иван Петров:lead,gidr02:Мария Сидорова:expert"
#
# Проверка в другом окне терминала:  python3 tools/check_service.py
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8080
ADMIN=""
EXPERTS=""
DATA_DIR="service_data"
AUTO_EXPORT_HOURS=6
HOST_BIND="0.0.0.0"

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --admin) ADMIN="$2"; shift 2 ;;
    --experts) EXPERTS="$2"; shift 2 ;;
    --data) DATA_DIR="$2"; shift 2 ;;
    --auto-export-hours) AUTO_EXPORT_HOURS="$2"; shift 2 ;;
    --local) HOST_BIND="127.0.0.1"; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Неизвестный параметр: $1 (см. --help)"; exit 2 ;;
  esac
done

gen_token() {  # gen_token префикс
  if command -v openssl >/dev/null 2>&1; then echo "$1$(openssl rand -hex 8)";
  else echo "$1$(python3 -c 'import secrets;print(secrets.token_hex(8))')"; fi
}

[ -n "$ADMIN" ]   || ADMIN="$(gen_token admin-)"
[ -n "$EXPERTS" ] || EXPERTS="$(gen_token gidr01-):Иван Петров:lead"

PY="python3"
command -v python3 >/dev/null 2>&1 || PY="python"
if ! "$PY" -c "import fastapi, uvicorn, wntr" >/dev/null 2>&1; then
  echo "Не хватает зависимостей. Выполните один раз:"
  echo "  $PY -m pip install -r requirements.txt"
  exit 1
fi

case "$DATA_DIR" in
  /*) DATA_PATH="$DATA_DIR" ;;          # абсолютный путь оставляем как есть
  *)  DATA_PATH="$PWD/$DATA_DIR" ;;
esac
export SERVICE_DATA="$DATA_PATH"
export ADMIN_TOKEN="$ADMIN"
export EXPERT_TOKENS="$EXPERTS"
export AUTO_EXPORT_HOURS="$AUTO_EXPORT_HOURS"
mkdir -p "$SERVICE_DATA"

cat <<EOF

Сервис запускается:
  интерфейс:      http://localhost:$PORT/
  админка:        http://localhost:$PORT/admin?token=$ADMIN
  проверка:       http://localhost:$PORT/health

Токен администратора (только для вас):
  $ADMIN

EOF

# персональные ссылки для гидравликов
IFS=',' read -ra CHUNKS <<< "$EXPERTS"
for chunk in "${CHUNKS[@]}"; do
  token="${chunk%%:*}"; rest="${chunk#*:}"
  name="${rest%%:*}"; role="${rest#*:}"; [ "$role" = "$name" ] && role="expert"
  printf 'Гидравлик: %s (%s)\n  персональная ссылка: http://localhost:%s/?token=%s\n' \
         "$name" "$role" "$PORT" "$token"
done

cat <<EOF

Проверка в другом окне:
  $PY tools/check_service.py --token <токен гидравлика> --admin $ADMIN
Остановить сервис: Ctrl+C

EOF

exec "$PY" -m uvicorn service.app:app --host "$HOST_BIND" --port "$PORT"
