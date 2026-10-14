"""Проверка «чистоты» данных: в обучении — только реальные данные.

Правило проекта: датасет обучения — это реальные скриншоты AquaBit и реальные ответы
(Gemini / инженера). Синтетика (демо-скриншоты для автотестов, образцы формата, фикстуры)
допустима **только в tests/fixtures/** и никогда не должна попадать в data/.

Что проверяет этот скрипт:
  1. data/screens/manifest.jsonl — сколько скриншотов, у всех ли есть ответы, какие группы;
  2. **утечку фикстур**: не похожи ли картинки датасета на синтетические из tests/fixtures
     (сравнение по dHash, порог 8 — как в остальном конвейере);
  3. «маркеры синтетики» в путях/идентификаторах записей (demo, test, fixture, synthetic, образец);
  4. посторонние *.jsonl в data/ с метками synthetic.

Запуск:
    python tools/check_data_purity.py
    python tools/check_data_purity.py --manifest data/screens/manifest.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import common            # noqa: E402
from src.vision import preprocess as pp   # noqa: E402

SYNTHETIC_MARKERS = ("demo", "synthetic", "fixture", "образец", "scr_", "dummy")
DHASH_LEAK_LIMIT = 8
FIXTURE_DIRS = ("tests/fixtures",)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _hash_int(value) -> int | None:
    """dHash в манифесте — hex-строка ('0180cc48…'); приводим к int для расстояния Хэмминга."""
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    try:
        return int(text, 16)
    except ValueError:
        return None


def fixture_hashes() -> dict[str, str]:
    """dHash всех синтетических картинок из tests/fixtures (индекс: хеш → путь)."""
    out: dict[str, str] = {}
    for d in FIXTURE_DIRS:
        root = common.ROOT / d
        if not root.exists():
            continue
        for f in sorted(root.rglob("*")):
            if f.is_file() and pp.is_image(f):
                try:
                    out[pp.dhash(f)] = str(f.relative_to(common.ROOT))
                except Exception:  # noqa: BLE001
                    continue
    return out


def check_screens(manifest: Path) -> int:
    """Возвращает число найденных проблем (0 — чисто)."""
    print("=" * 78)
    print("ДАТАСЕТ СКРИНШОТОВ (main-трек: скриншоты → ответ)")
    print("=" * 78)
    if not manifest.exists():
        print(f"{common.rel_to_root(manifest)}: нет — датасет ещё не импортирован.")
        print("  порядок: data/screens/raw/ → python -m src.dataset.import_screenshots --src data/screens/raw")
        return 0

    rows = _read_jsonl(manifest)
    problems = 0
    if not rows:
        print(f"{common.rel_to_root(manifest)}: пусто.")
        return 0

    no_answer = [r for r in rows if not (r.get("answer") or "").strip()]
    groups: dict[str, int] = {}
    for r in rows:
        groups[str(r.get("session") or "—")] = groups.get(str(r.get("session") or "—"), 0) + 1

    print(f"  скриншотов:          {len(rows)}")
    print(f"  с ответом:           {len(rows) - len(no_answer)}  (без ответа: {len(no_answer)})")
    print(f"  групп (сессий):      {len(groups)}")
    top = sorted(groups.items(), key=lambda kv: -kv[1])[:5]
    print("  крупнейшие группы:   " + ", ".join(f"{k} ({v})" for k, v in top))

    # 1) маркеры синтетики в id/путях
    flagged = []
    for r in rows:
        hay = " ".join(str(r.get(k, "")) for k in ("id", "image", "image_abs")).lower()
        if any(m in hay for m in SYNTHETIC_MARKERS):
            flagged.append(r.get("id"))
    if flagged:
        problems += len(flagged)
        print(f"  ⚠ похожи на синтетику/фикстуры (проверить!): {', '.join(map(str, flagged[:8]))}"
              + (" …" if len(flagged) > 8 else ""))
    else:
        print("  ✓ маркеров синтетики в записях нет")

    # 2) утечка фикстур по картинкам (dHash)
    fixes = fixture_hashes()
    if fixes:
        leaks = []
        for r in rows:
            h = r.get("dhash")
            img = Path(str(r.get("image_abs") or "")) if r.get("image_abs") else None
            if not h and img and img.exists():
                try:
                    h = pp.dhash(img)
                except Exception:  # noqa: BLE001
                    h = None
            hi = _hash_int(h)
            if hi is None:
                continue
            for fh, fpath in fixes.items():
                fi = _hash_int(fh)
                if fi is not None and bin(hi ^ fi).count("1") <= DHASH_LEAK_LIMIT:
                    leaks.append((r.get("id"), fpath))
        if leaks:
            problems += len(leaks)
            print("  ⚠ в датасет попали кадры, похожие на синтетические фикстуры:")
            for rid, fpath in leaks[:8]:
                print(f"      {rid} ≈ {fpath}")
        else:
            print(f"  ✓ утечек из tests/fixtures не найдено (сверено с {len(fixes)} фикстурами)")
    else:
        print("  · синтетических картинок в tests/fixtures нет — сверять нечего")

    # 3) посторонние сплиты старого трека
    for f in sorted((common.ROOT / "data").glob("**/*.jsonl")):
        if f.name == "manifest.jsonl":
            continue
        rel = str(f.relative_to(common.ROOT))
        if "screens" not in rel:
            synth = [r for r in _read_jsonl(f) if (r.get("meta") or {}).get("synthetic")]
            print(f"  ⚠ посторонний файл данных {rel}: строк {len(synth)} синтетики"
                  if synth else f"  · {rel}: строк без метки синтетики")

    print()
    if problems == 0:
        print("ИТОГ: датасет чистый — в обучение идут только реальные материалы заказчика.")
    else:
        print(f"ИТОГ: найдено проблем: {problems}. Исправьте до запуска обучения.")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Чистота данных: в обучении — только реальные данные")
    ap.add_argument("--manifest", default="data/screens/manifest.jsonl")
    args = ap.parse_args()
    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = common.ROOT / manifest
    problems = check_screens(manifest)
    print("\nНапоминание: тестовые фикстуры лежат в tests/fixtures/ и в датасет не попадают.")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
