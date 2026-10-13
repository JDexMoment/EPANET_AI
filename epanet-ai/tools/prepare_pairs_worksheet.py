"""Рабочий лист для сборки пар «скриншот + ответ» вручную.

Как это работает у вас на машине:
  1. делаете скриншоты AquaBit в папку (например, D:\\Семей\\скрины\\), имена любые;
  2. запускаете этот скрипт — он создаст:
        <out>/answers/<имя>.txt   — пустой файл под ответ (скопировать из Gemini);
        <out>/pairs.csv           — таблицу пар со всеми колонками;
  3. открываете каждый скриншот, задаёте Gemini вопрос, копируете ответ в .txt
     (или прямо в столбец answer в pairs.csv — что удобнее);
  4. запускаете импорт:
        python -m src.dataset.import_screenshots --src <out> --summary
        python -m src.dataset.check_screenshot_pairs --manifest <out>/manifest.jsonl
     Импорт сам сшивает картинки и ответы (по имени) и заполняет манифест.

Повторный запуск безопасен: заполненные ответы не перезаписываются, новые скриншоты
добавляются. Так можно пополнять датасет порциями.

Запуск:
    python tools/prepare_pairs_worksheet.py --shots D:\\Семей\\скрины --out D:\\Семей\\dataset
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.vision import preprocess as pp  # noqa: E402

COLUMNS = ["image", "question", "answer", "session", "window_type", "result_time", "screen_text", "notes"]
ANSWER_STUB = (
    "; Ответ Gemini на этот скриншот. Вставьте текст ниже этой строки.\n"
    "; Вопрос: {question}\n"
    "; Полезно указать: тип окна, время расчёта, проект.\n\n"
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Создать рабочий лист «скриншоты → ответы»")
    ap.add_argument("--shots", required=True, help="папка со скриншотами (png/jpg)")
    ap.add_argument("--out", default=None, help="куда собрать датасет (по умолчанию — рядом с --shots)")
    ap.add_argument("--question", default="Проанализируй картинку.",
                    help="вопрос, который задаёте Gemini (один и тот же для всех)")
    args = ap.parse_args()

    shots = Path(args.shots).expanduser()
    if not shots.is_dir():
        print(f"нет папки со скриншотами: {shots}")
        return 2
    out = Path(args.out).expanduser() if args.out else shots.parent / (shots.name + "_dataset")
    answers = out / "answers"
    answers.mkdir(parents=True, exist_ok=True)

    images = sorted(f for f in shots.iterdir() if f.is_file() and pp.is_image(f))
    if not images:
        print(f"в {shots} не найдено изображений ({', '.join(sorted(pp.IMAGE_SUFFIXES))})")
        return 2

    # уже заполненные ответы (если лист создаётся повторно)
    known: dict[str, str] = {}
    for f in answers.glob("*.txt"):
        txt = f.read_text(encoding="utf-8", errors="replace")
        body = "\n".join(l for l in txt.splitlines() if not l.strip().startswith(";")).strip()
        if body:
            known[f.stem] = body

    created = kept = 0
    for img in images:
        ans = answers / f"{img.stem}.txt"
        if not ans.exists():
            ans.write_text(ANSWER_STUB.format(question=args.question), encoding="utf-8")
            created += 1
        else:
            kept += 1

    csv_path = out / "pairs.csv"
    rows: dict[str, dict] = {}
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("image"):
                    rows[Path(r["image"]).stem] = r
    for img in images:
        row = rows.get(img.stem, {c: "" for c in COLUMNS})
        row["image"] = img.name
        row["question"] = row.get("question") or args.question
        if not (row.get("answer") or "").strip() and img.stem in known:
            row["answer"] = known[img.stem]
        rows[img.stem] = row
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for stem in sorted(rows):
            w.writerow(rows[stem])

    filled = sum(1 for r in rows.values() if (r.get("answer") or "").strip())
    print("=" * 74)
    print("РАБОЧИЙ ЛИСТ ПАР «СКРИНШОТ + ОТВЕТ»")
    print("=" * 74)
    print(f"  скриншотов найдено:   {len(images)}")
    print(f"  файлов ответа создано:{created:>4} (уже было: {kept})")
    print(f"  ответов заполнено:    {filled}")
    print(f"  таблица:              {csv_path}")
    print(f"  папка ответов:        {answers}")
    print()
    print("  дальше: вставить ответы Gemini в .txt (или в столбец answer таблицы) и запустить")
    print(f"      python -m src.dataset.import_screenshots --src \"{out}\" --summary")
    print(f"      python -m src.dataset.check_screenshot_pairs --manifest \"{out}/manifest.jsonl\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
