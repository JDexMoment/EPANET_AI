"""Общие утилиты проекта: пути, конфиги, JSON, время, хеши."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import random
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def path(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


def ensure_dir(p: Path | str) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_yaml(rel_or_abs: str | Path) -> dict:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = ROOT / p
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_json(rel_or_abs: str | Path) -> dict:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = ROOT / p
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(rel_or_abs: str | Path, obj) -> Path:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = ROOT / p
    ensure_dir(p.parent)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return p


def write_jsonl(rel_or_abs: str | Path, rows: list[dict]) -> Path:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = ROOT / p
    ensure_dir(p.parent)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def read_jsonl(rel_or_abs: str | Path) -> list[dict]:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = ROOT / p
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def sha256_file(p: Path | str) -> str:
    p = Path(p)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def rng(seed: int) -> random.Random:
    return random.Random(seed)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def epanet_tmp_prefix(tag: str = "run") -> str:
    """Префикс временных файлов EPANET (temp.inp/.rpt/.bin) ВНЕ репозитория.

    WNTR пишет эти файлы в текущий каталог; если запускать из корня проекта,
    они попадают в репозиторий. Поэтому всегда направляем их в системный temp.
    """
    d = Path(tempfile.gettempdir()) / "epanet_ai_tmp"
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(tag))[:48]
    return str(d / safe)


def env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default) in ("1", "true", "True", "yes")
