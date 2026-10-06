"""Настройки сервиса сбора данных от инженеров-гидравликов.

Всё берётся из переменных окружения (см. deploy/service.env.example), с безопасными
значениями по умолчанию для локального запуска.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]        # корень epanet-ai
DATA = Path(os.environ.get("SERVICE_DATA", ROOT / "service_data"))

HOST = os.environ.get("SERVICE_HOST", "0.0.0.0")
PORT = int(os.environ.get("SERVICE_PORT", "8080"))
PUBLIC_URL = os.environ.get("SERVICE_PUBLIC_URL", "").rstrip("/")

# ── доступ
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or "admin-" + secrets.token_urlsafe(12)
# эксперт: EXPERT_TOKENS="token1:Иван Петров:lead,token2:Мария:expert"
def _parse_experts(raw: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split(":")]
        token = parts[0]
        out[token] = {
            "expert_id": (parts[1] or "expert").strip() if len(parts) > 1 else "expert",
            "role": parts[2] if len(parts) > 2 else "expert",
        }
    return out


EXPERT_TOKENS = _parse_experts(os.environ.get("EXPERT_TOKENS", ""))

# ── пределы (анти-абьюз)
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "60"))
ALLOWED_EXT = {".inp", ".net", ".epanet", ".zip"}
MAX_ANNOTATIONS_PER_HOUR = int(os.environ.get("MAX_ANNOTATIONS_PER_HOUR", "60"))
MAX_UPLOADS_PER_DAY = int(os.environ.get("MAX_UPLOADS_PER_DAY", "40"))

# ── автономная работа: авто-экспорт и резервные копии
AUTO_EXPORT_HOURS = float(os.environ.get("AUTO_EXPORT_HOURS", "6"))
KEEP_EXPORTS = int(os.environ.get("KEEP_EXPORTS", "30"))
BACKUP_CMD = os.environ.get("BACKUP_CMD", "")     # например: rclone copy {file} myremote:epanet-ai
ANNOUNCE_WEBHOOK = os.environ.get("ANNOUNCE_WEBHOOK", "")   # необязательный вебхук после экспорта

# ── расчёт
RUN_SIMULATION = os.environ.get("RUN_SIMULATION", "1") not in ("0", "false", "no")
CONTEXT_MODES = [m.strip() for m in os.environ.get(
    "CONTEXT_MODES", "whats_happening,explain_object,find_problems,why_happened,make_report").split(",") if m.strip()]

DB_PATH = DATA / "service.sqlite3"
UPLOADS = DATA / "uploads"          # исходные файлы по моделям
MODELS = DATA / "models"            # модель как «сценарий» (inp, results/, derived/)
EXPORTS = DATA / "exports"          # автоэкспорты и бэкапы
LOGS = DATA / "logs"
