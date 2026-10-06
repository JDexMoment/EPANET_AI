#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Установка сервиса сбора данных на чистый сервер Ubuntu 22.04 / 24.04 (VPS).
# Делает всё сама: docker, файрвол, каталог данных, .env с токенами, автозапуск.
#
# Запуск на сервере (под root или через sudo):
#     bash install_vps.sh epanet.example.com
#     bash install_vps.sh              # без домена, сайт на http://IP
#
# После установки скрипт распечатает: адрес сервиса, токен админа, токены инженеров.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN="${1:-}"
APP_DIR="/opt/epanet-ai"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

say() { printf "\n\033[1;36m%s\033[0m\n" "$*"; }

say "1/6 · системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ufw openssl >/dev/null

say "2/6 · docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true

say "3/6 · файрвол (22, 80, 443)"
ufw allow 22/tcp >/dev/null 2>&1 || true
ufw allow 80/tcp >/dev/null 2>&1 || true
ufw allow 443/tcp >/dev/null 2>&1 || true
yes | ufw enable >/dev/null 2>&1 || true

say "4/6 · файлы приложения в $APP_DIR"
mkdir -p "$APP_DIR"
if [ "$REPO_DIR" != "$APP_DIR" ]; then
  # копируем проект (без данных и мусора)
  rsync -a --delete \
    --exclude 'service_data' --exclude '__pycache__' --exclude '.git' \
    --exclude 'data/scenarios' --exclude 'outputs' \
    "$REPO_DIR"/ "$APP_DIR"/ 2>/dev/null || {
      cp -r "$REPO_DIR"/. "$APP_DIR"/
      rm -rf "$APP_DIR/service_data" "$APP_DIR/.git"
    }
fi
mkdir -p "$APP_DIR/deploy/data"

say "5/6 · конфигурация (deploy/service.env)"
ENV_FILE="$APP_DIR/deploy/service.env"
if [ ! -f "$ENV_FILE" ]; then
  ADMIN_TOKEN="$(openssl rand -hex 16)"
  EXP1_TOKEN="$(openssl rand -hex 12)"
  EXP2_TOKEN="$(openssl rand -hex 12)"
  EXP3_TOKEN="$(openssl rand -hex 12)"
  SITE="${DOMAIN:-:80}"
  # публичный адрес для персональных ссылок инженерам (если домен задан — https)
  if [ -n "${DOMAIN:-}" ]; then PUBLIC_URL="https://$DOMAIN"; else PUBLIC_URL=""; fi
  cat > "$ENV_FILE" <<EOF
ADMIN_TOKEN=$ADMIN_TOKEN
EXPERT_TOKENS=$EXP1_TOKEN:Инженер-1:lead,$EXP2_TOKEN:Инженер-2:expert,$EXP3_TOKEN:Инженер-3:expert
SITE_ADDRESS=$SITE
SERVICE_PUBLIC_URL=$PUBLIC_URL
MAX_UPLOAD_MB=60
MAX_ANNOTATIONS_PER_HOUR=60
MAX_UPLOADS_PER_DAY=40
AUTO_EXPORT_HOURS=6
KEEP_EXPORTS=30
BACKUP_CMD=
ANNOUNCE_WEBHOOK=
RUN_SIMULATION=1
CONTEXT_MODES=whats_happening,explain_object,find_problems,why_happened,make_report
EOF
  chmod 600 "$ENV_FILE"
  echo "  создан $ENV_FILE"
else
  echo "  $ENV_FILE уже существует — оставляю как есть"
fi

say "6/6 · запуск контейнеров"
cd "$APP_DIR/deploy"
docker compose --env-file service.env up -d --build

# автозапуск после перезагрузки сервера (compose уже с restart: always)
cat > /etc/systemd/system/epanet-ai.service <<EOF
[Unit]
Description=EPANET-AI collection service
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR/deploy
ExecStart=/usr/bin/docker compose --env-file service.env up -d
ExecStop=/usr/bin/docker compose --env-file service.env down

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable epanet-ai.service >/dev/null 2>&1 || true

# ежедневная резервная копия (архив данных вне контейнера)
if ! crontab -l 2>/dev/null | grep -q "epanet-ai-backup"; then
  (crontab -l 2>/dev/null; echo "30 3 * * * bash $APP_DIR/deploy/backup.sh >> $APP_DIR/deploy/data/logs/backup.log 2>&1 # epanet-ai-backup") | crontab -
fi

IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo 'IP-сервера')"
ADDR="${DOMAIN:+https://$DOMAIN}"
ADDR="${ADDR:-http://$IP}"

if [ -n "$DOMAIN" ]; then
  say "Проверка сертификата (может занять до минуты)"
  sleep 20
  curl -fsS "https://$DOMAIN/health" >/dev/null && echo "  TLS и сервис отвечают ✓" || \
    echo "  сертификат ещё выпускается — проверьте позже: docker compose logs caddy"
fi

say "ГОТОВО"
cat <<EOF
  Сервис:            $ADDR
  Интерфейс инженера:$ADDR/
  Админка:           $ADDR/admin
  Файл конфигурации: $ENV_FILE

  $(grep -E '^(ADMIN_TOKEN|EXPERT_TOKENS)=' "$ENV_FILE" | sed 's/^/  /')

  Полезные команды (в $APP_DIR/deploy):
    docker compose --env-file service.env ps          # состояние
    docker compose --env-file service.env logs -f app # логи
    docker compose --env-file service.env restart app # перезапуск

  Забрать собранные данные к себе (на своём компьютере):
    python tools/pull_collected.py --url $ADDR --token <ADMIN_TOKEN> --pipeline

  Сервер работает автономно: контейнеры перезапускаются сами (restart: always),
  архив для обучения собирается каждые AUTO_EXPORT_HOURS часов,
  резервная копия данных делается ежедневно в 03:30 (deploy/backup.sh).
EOF
