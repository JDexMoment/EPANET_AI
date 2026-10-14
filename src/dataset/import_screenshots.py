"""Импорт присланного датасета «скриншоты + ответы Gemini» в единый манифест.

Датасеты приходят в разных раскладках — поддерживаем все типичные:

  A) одним файлом-выгрузкой:  export.jsonl / export.json / export.csv
     поля-синонимы: image|file|screenshot|img|path  +  answer|response|golden|gold|text|ответ,
     необязательно: question|prompt|вопрос, session|group|модель|model, visible_text|ocr.
  B) ответы отдельными файлами:  answers/<имя_картинки>.txt|md|json   (json: поле answer/text)
  C) ответ рядом с картинкой:    images/foo.png + images/foo.txt|foo.md|foo.json
  D) текст, «видимый» на экране (если заказчик приложил OCR): ocr/<имя>.txt или <имя>.ocr.txt

Результат — `data/screens/manifest.jsonl`: по строке на скриншот, со всеми путями,
отпечатком (dHash), группой (сессия/папка) и текстом ответа. Дальше его проверяет
`check_screenshot_pairs`, режет на сплиты `build_vl_dataset`.

Запуск:
    python -m src.dataset.import_screenshots --src data/screens/raw
    python -m src.dataset.import_screenshots --src ~/датасет --out data/screens/manifest.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .. import common
from ..vision import preprocess as pp

IMAGE_FIELDS = ("image", "file", "screenshot", "img", "path", "image_path", "файл", "картинка")
ANSWER_FIELDS = ("answer", "response", "golden", "gold", "text", "output", "answer_text", "ответ")
QUESTION_FIELDS = ("question", "prompt", "query", "вопрос", "instruction")
GROUP_FIELDS = ("session", "group", "model", "network", "case", "сессия", "группа", "модель")
VISIBLE_FIELDS = ("visible_text", "ocr", "ocr_text", "screen_text", "текст_экрана")


def _pick(row: dict, fields: tuple[str, ...]) -> str:
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for f in fields:
        if f in low and low[f] not in (None, ""):
            return str(low[f]).strip()
    return ""


def _read_index(path: Path) -> list[dict]:
    """Читает файл-выгрузку (jsonl / json / csv) в список словарей."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(r) for r in csv.DictReader(f)]
    if suffix == ".jsonl":
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        for key in ("items", "data", "samples", "records", "examples"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []


def _read_answer_file(path: Path) -> tuple[str, str, str]:
    """Возвращает (ответ, вопрос, видимый текст) из файла-ответа."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text.strip(), "", ""
        if isinstance(data, dict):
            ans = _pick(data, ANSWER_FIELDS) or text.strip()
            return ans, _pick(data, QUESTION_FIELDS), _pick(data, VISIBLE_FIELDS)
    return text.strip(), "", ""


def _find_index(src: Path) -> Path | None:
    for pattern in ("*.jsonl", "*.json", "*.csv"):
        for p in sorted(src.glob(pattern)):
            if p.name.lower().startswith(("manifest", "summary")):
                continue
            try:
                rows = _read_index(p)
            except Exception:  # noqa: BLE001
                continue
            if rows and any(_pick(r, IMAGE_FIELDS) and _pick(r, ANSWER_FIELDS) for r in rows):
                return p
    return None


def collect(src: Path, default_question: str) -> tuple[list[dict], list[str]]:
    """Собирает записи манифеста и список замечаний (что не удалось сшить)."""
    notes: list[str] = []
    images = sorted(p for p in src.rglob("*") if p.is_file() and pp.is_image(p))

    index_rows: dict[str, dict] = {}       # имя файла → строка выгрузки
    index_path = _find_index(src) if src.is_dir() else None
    if index_path:
        for row in _read_index(index_path):
            img_field = _pick(row, IMAGE_FIELDS)
            if not img_field:
                continue
            index_rows[Path(img_field).name] = row

    records: list[dict] = []
    for img in images:
        stem, name = img.stem, img.name
        answer = question = visible = ""
        layout = ""

        if name in index_rows:
            row = index_rows[name]
            answer = _pick(row, ANSWER_FIELDS)
            question = _pick(row, QUESTION_FIELDS)
            visible = _pick(row, VISIBLE_FIELDS)
            group_raw = _pick(row, GROUP_FIELDS)
            layout = f"index:{index_path.name}"
        else:
            group_raw = ""

        # B) answers/<stem>.txt и D) ocr/<stem>.txt — ищем в самой папке и рядом с src
        if not answer:
            for cand in (img.with_suffix(".txt"), img.with_suffix(".md"), img.with_suffix(".json"),
                         img.parent / "answers" / f"{stem}.txt", img.parent / "answers" / f"{stem}.md",
                         img.parent / "answers" / f"{stem}.json",
                         src / "answers" / f"{stem}.txt", src / "answers" / f"{stem}.md",
                         src / "answers" / f"{stem}.json"):
                if cand.exists() and cand.stat().st_size:
                    answer, question_2, visible_2 = _read_answer_file(cand)
                    question = question or question_2
                    visible = visible or visible_2
                    layout = layout or f"answer_file:{cand.name}"
                    break
        if not visible:
            for cand in (img.parent / "ocr" / f"{stem}.txt", img.with_suffix(".ocr.txt"),
                         src / "ocr" / f"{stem}.txt"):
                if cand.exists() and cand.stat().st_size:
                    visible = cand.read_text(encoding="utf-8", errors="replace").strip()
                    break

        info = pp.image_info(img)
        rec = {
            "id": stem,
            "image": str(img.resolve().relative_to(common.ROOT)) if str(img.resolve()).startswith(str(common.ROOT))
                     else str(img),
            "image_abs": str(img.resolve()),
            "question": question or default_question,
            "answer": answer,
            "visible_text": visible,
            "session": group_raw or str(img.parent.resolve().relative_to(src.resolve())) if src in img.parents else group_raw,
            "width": info["width"], "height": info["height"], "aspect": info["aspect"],
            "bytes": info["bytes"],
            "sha256_16": common.sha256_file(img),
            "dhash": pp.dhash(img),
            "source": {"layout": layout or "none", "image_file": name},
        }
        records.append(rec)
        if not answer:
            notes.append(f"нет ответа для {name} (искали: рядом с картинкой, в answers/, в выгрузке)")
    return records, notes


def main() -> None:
    ap = argparse.ArgumentParser(description="Импорт датасета «скриншоты + ответы» в манифест")
    ap.add_argument("--src", default="data/screens/raw", help="папка с присланным датасетом")
    ap.add_argument("--out", default="data/screens/manifest.jsonl")
    ap.add_argument("--question", default=None,
                    help="вопрос по умолчанию (по умолчанию берётся из configs/vision.yaml)")
    ap.add_argument("--summary", default=None, help="куда записать сводку (JSON)")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/vision.yaml")
    question = args.question or cfg["question"]["default"]

    src = Path(args.src).expanduser()
    if not src.exists():
        print(f"Нет папки {src}. Положите туда присланный датасет (картинки + ответы).")
        print("Раскладки, которые понимает импорт, описаны в шапке src/dataset/import_screenshots.py")
        return

    records, notes = collect(src, question)
    if not records:
        print(f"В {src} не найдено ни одного изображения ({', '.join(sorted(pp.IMAGE_SUFFIXES))}).")
        return

    common.write_jsonl(common.ROOT / args.out, records)
    with_answer = sum(1 for r in records if r["answer"])
    with_visible = sum(1 for r in records if r["visible_text"])
    layouts: dict[str, int] = {}
    for r in records:
        key = r["source"]["layout"].split(":")[0]
        layouts[key] = layouts.get(key, 0) + 1
    sessions = len({r["session"] for r in records})

    summary = {"src": str(src), "records": len(records), "with_answer": with_answer,
               "with_visible_text": with_visible, "sessions": sessions,
               "layouts": layouts, "notes": notes[:50],
               "out": args.out}
    if args.summary:
        common.write_json(common.ROOT / args.summary, summary)

    print("=" * 78)
    print(f"ИМПОРТ ДАТАСЕТА · {src}")
    print("=" * 78)
    print(f"  скриншотов:            {len(records)}")
    print(f"  с ответом:             {with_answer}  (без ответа: {len(records) - with_answer})")
    print(f"  с текстом экрана:      {with_visible}  (нужен для проверки чисел на выдуманность)")
    print(f"  групп (сессий):        {sessions}")
    print(f"  раскладки:             {layouts}")
    print(f"  манифест:              {args.out}")
    for n in notes[:8]:
        print(f"  ! {n}")
    if len(notes) > 8:
        print(f"  ! ... ещё {len(notes) - 8} замечаний")
    print("\nДальше:  python -m src.dataset.check_screenshot_pairs")


if __name__ == "__main__":
    main()
