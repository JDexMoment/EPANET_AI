#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Резервная копия данных сервиса сбора (БД + загруженные и очищенные модели).
# Запускается по крону каждый день (ставится install_vps.sh), можно и вручную.
#
# Раскладка: deploy/data/backups/epanet-ai-ГГГГММДД-ЧЧММ.tar.gz, хранится KEEP штук.
# Если в service.env задан BACKUP_CMD — копия сразу уходит наружу (rclone/S3/scp).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$HERE/data"
BACKUP_DIR="$DATA_DIR/backups"
KEEP="${KEEP_BACKUPS:-14}"
STAMP="$(date +%Y%m%d-%H%M)"
ARCHIVE="$BACKUP_DIR/epanet-ai-$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR" "$DATA_DIR/logs"

echo "$(date -Is) · бэкап данных сервиса"
tar -czf "$ARCHIVE" \
  -C "$DATA_DIR" \
  --exclude='backups' \
  --exclude='logs/*.log' \
  service.sqlite3 uploads models exports 2>/dev/null || \
  tar -czf "$ARCHIVE" -C "$DATA_DIR" service.sqlite3 2>/dev/null || true

echo "  создан $(du -h "$ARCHIVE" | cut -f1) → $ARCHIVE"

# чистим старые
ls -1t "$BACKUP_DIR"/epanet-ai-*.tar.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | xargs -r rm -f

# копия наружу
if [ -f "$HERE/service.env" ]; then
  # shellcheck disable=SC1091
  BACKUP_CMD="$(grep -E '^BACKUP_CMD=' "$HERE/service.env" | cut -d= -f2- || true)"
  if [ -n "${BACKUP_CMD:-}" ]; then
    echo "  копирую наружу: ${BACKUP_CMD//\{file\}/$ARCHIVE}"
    bash -c "${BACKUP_CMD//\{file\}/$ARCHIVE}" || echo "  ! внешнее копирование не удалось"
  fi
fi
echo "  готово"
