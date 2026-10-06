"""Хранилище: SQLite (метаданные, аннотации, события) + файлы на диске.

Схема сознательно простая: одна таблица моделей, одна таблица аннотаций, журнал событий.
Выгрузка в датасет обучения делается отдельно (service/export.py) — из тех же строк.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Iterable

from . import config

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS experts (
    token TEXT PRIMARY KEY,
    expert_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'expert',
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    uploaded_by TEXT,
    filename TEXT,
    orig_format TEXT,
    sha256 TEXT,
    size_bytes INTEGER,
    status TEXT,                -- ok | failed | no_analysis
    error TEXT,
    clean_inp TEXT,
    n_nodes INTEGER,
    n_links INTEGER,
    kpi_json TEXT,
    alerts_json TEXT,
    objects_json TEXT,
    warnings_json TEXT,
    conversion_json TEXT,
    meta_json TEXT
);
CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    expert_id TEXT NOT NULL,
    kind TEXT NOT NULL,          -- element_problem | report | qa
    mode TEXT NOT NULL,          -- режимы датасета (whats_happening, explain_object, …)
    object_id TEXT,
    question TEXT,
    answer TEXT,
    observations TEXT,
    causes TEXT,
    checks TEXT,
    recommendations TEXT,
    limitations TEXT,
    report_markdown TEXT,
    category TEXT,
    severity TEXT,
    confidence TEXT,
    evidence_refs TEXT,
    time_spent_min INTEGER,
    number_check_json TEXT,
    exported_at TEXT,
    FOREIGN KEY (model_id) REFERENCES models(id)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_ann_model ON annotations(model_id);
CREATE INDEX IF NOT EXISTS idx_ann_expert ON annotations(expert_id);
CREATE INDEX IF NOT EXISTS idx_models_sha ON models(sha256);
"""


def connect() -> sqlite3.Connection:
    config.DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init() -> None:
    for d in (config.DATA, config.UPLOADS, config.MODELS, config.EXPORTS, config.LOGS):
        d.mkdir(parents=True, exist_ok=True)
    with _LOCK, connect() as conn:
        conn.executescript(SCHEMA)
        for token, rec in config.EXPERT_TOKENS.items():
            conn.execute(
                "INSERT OR IGNORE INTO experts(token, expert_id, role, created_at) VALUES (?,?,?,datetime('now'))",
                (token, rec["expert_id"], rec["role"]))


# ─────────────────────────────── эксперты
def expert_by_token(token: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM experts WHERE token=? AND active=1", (token,)).fetchone()
    return dict(row) if row else None


def list_experts() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT e.*, (SELECT COUNT(*) FROM annotations a WHERE a.expert_id = e.expert_id) AS n_annotations
               FROM experts e ORDER BY e.created_at""").fetchall()
    return [dict(r) for r in rows]


def add_expert(token: str, expert_id: str, role: str = "expert") -> dict:
    with _LOCK, connect() as conn:
        conn.execute("INSERT OR REPLACE INTO experts(token, expert_id, role, created_at, active) "
                     "VALUES (?,?,?,datetime('now'),1)", (token, expert_id, role))
    return {"token": token, "expert_id": expert_id, "role": role}


# ─────────────────────────────── модели
def create_model(rec: dict) -> None:
    cols = ["id", "created_at", "uploaded_by", "filename", "orig_format", "sha256", "size_bytes",
            "status", "error", "clean_inp", "n_nodes", "n_links", "kpi_json", "alerts_json",
            "objects_json", "warnings_json", "conversion_json", "meta_json"]
    vals = [rec.get(c) for c in cols]
    with _LOCK, connect() as conn:
        conn.execute(f"INSERT OR REPLACE INTO models({','.join(cols)}) "
                     f"VALUES ({','.join('?' * len(cols))})", vals)


def update_model(model_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _LOCK, connect() as conn:
        conn.execute(f"UPDATE models SET {sets} WHERE id=?", [*fields.values(), model_id])


def get_model(model_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    return dict(row) if row else None


def find_model_by_sha(sha: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM models WHERE sha256=? ORDER BY created_at DESC LIMIT 1",
                           (sha,)).fetchone()
    return dict(row) if row else None


def list_models(limit: int = 200) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT m.*, (SELECT COUNT(*) FROM annotations a WHERE a.model_id = m.id) AS n_annotations
               FROM models m ORDER BY m.created_at DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────── аннотации
ANN_COLS = ["id", "created_at", "updated_at", "model_id", "expert_id", "kind", "mode", "object_id",
            "question", "answer", "observations", "causes", "checks", "recommendations",
            "limitations", "report_markdown", "category", "severity", "confidence", "evidence_refs",
            "time_spent_min", "number_check_json"]


def save_annotation(rec: dict) -> dict:
    cols = [c for c in ANN_COLS if c in rec]
    with _LOCK, connect() as conn:
        conn.execute(f"INSERT OR REPLACE INTO annotations({','.join(cols)}) "
                     f"VALUES ({','.join('?' * len(cols))})", [rec[c] for c in cols])
    return rec


def get_annotation(ann_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM annotations WHERE id=?", (ann_id,)).fetchone()
    return dict(row) if row else None


def list_annotations(model_id: str | None = None, expert_id: str | None = None,
                     only_unexported: bool = False, limit: int = 1000) -> list[dict]:
    q = ("SELECT a.*, m.filename AS model_filename FROM annotations a "
         "LEFT JOIN models m ON m.id = a.model_id WHERE 1=1")
    args: list[Any] = []
    if model_id:
        q += " AND a.model_id=?"
        args.append(model_id)
    if expert_id:
        q += " AND a.expert_id=?"
        args.append(expert_id)
    if only_unexported:
        q += " AND (a.exported_at IS NULL OR a.exported_at='')"
    q += " ORDER BY a.created_at DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        rows = conn.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def mark_exported(ids: Iterable[str], ts: str) -> int:
    ids = list(ids)
    if not ids:
        return 0
    with _LOCK, connect() as conn:
        conn.executemany("UPDATE annotations SET exported_at=? WHERE id=?", [(ts, i) for i in ids])
    return len(ids)


# ─────────────────────────────── события
def log_event(event: str, actor: str | None = None, **payload: Any) -> None:
    """Журнал событий. Имя параметра — event, чтобы payload мог содержать поле kind."""
    import json
    with _LOCK, connect() as conn:
        conn.execute("INSERT INTO events(ts, kind, actor, payload_json) VALUES (datetime('now'),?,?,?)",
                     (event, actor, json.dumps(payload, ensure_ascii=False)))


def list_events(limit: int = 200) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict:
    with connect() as conn:
        g = lambda q, *a: conn.execute(q, a).fetchone()[0]  # noqa: E731
        return {
            "models": g("SELECT COUNT(*) FROM models"),
            "models_ok": g("SELECT COUNT(*) FROM models WHERE status='ok'"),
            "annotations": g("SELECT COUNT(*) FROM annotations"),
            "annotations_unexported": g("SELECT COUNT(*) FROM annotations WHERE exported_at IS NULL OR exported_at=''"),
            "experts": g("SELECT COUNT(*) FROM experts WHERE active=1"),
            "reports": g("SELECT COUNT(*) FROM annotations WHERE kind='report'"),
            "qa": g("SELECT COUNT(*) FROM annotations WHERE kind='qa'"),
            "element_problems": g("SELECT COUNT(*) FROM annotations WHERE kind='element_problem'"),
        }
