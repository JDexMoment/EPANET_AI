"""Контроль качества датасета «скриншоты + ответы Gemini».

Что делает (по каждому скриншоту):
  • ищет полные дубли (sha256) и ПОЧТИ одинаковые кадры (dHash) — они
    объединяются в группу, чтобы train и test не пересекались;
  • проверяет сам скриншот: битый файл, слишком мелкий, странные пропорции;
  • проверяет «золотой» ответ: пустой, отказ («не могу определить»), слишком
    короткий/длинный, не по-русски, обрывки markdown;
  • сверяет числа ответа с текстом, который реально видно на экране (OCR):
    числа, которых на экране нет, — кандидаты в ошибки Gemini, их видно списком.

Результат: тот же манифест с полем `qa` + отчёт `data/screens/qa_report.json`.
Код возврата 1 при блокирующих проблемах (можно использовать как ворота приёмки).

Запуск:
    python -m src.dataset.check_screenshot_pairs
    python -m src.dataset.check_screenshot_pairs --manifest data/screens/manifest.jsonl --strict
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from .. import common
from ..vision import preprocess as pp

CYR = re.compile(r"[а-яё]", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)?")
MD_FENCE = re.compile(r"```|^\s*[#*>-]\s", re.M)


def _words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", ".") for m in NUM.finditer(text or "")}


def review(rec: dict, cfg: dict) -> dict:
    q = cfg["quality"]
    flags: list[str] = []
    blocking: list[str] = []

    img_path = Path(rec.get("image_abs") or rec["image"])
    if not img_path.exists():
        blocking.append("файл изображения не найден")
    else:
        try:
            pp.image_info(img_path)
        except Exception as e:  # noqa: BLE001
            blocking.append(f"картинка не открывается: {type(e).__name__}")

    if min(rec.get("width", 0), rec.get("height", 0)) < q["min_side_px"]:
        flags.append(f"мелкий скриншот {rec.get('width')}×{rec.get('height')} (меньше {q['min_side_px']} px)")
    if rec.get("aspect", 0) > q["max_aspect_ratio"] or (rec.get("aspect") and rec["aspect"] < 1 / q["max_aspect_ratio"]):
        flags.append(f"необычные пропорции ({rec.get('aspect')})")

    answer = (rec.get("answer") or "").strip()
    words = _words(answer)
    low = answer.lower()
    if not answer:
        blocking.append("пустой ответ")
    else:
        if words < q["min_answer_words"]:
            flags.append(f"короткий ответ: {words} слов (норма ≥ {q['min_answer_words']})")
        if words > q["max_answer_words"]:
            flags.append(f"очень длинный ответ: {words} слов (норма ≤ {q['max_answer_words']})")
        for marker in q["refusal_markers"]:
            if marker in low:
                blocking.append(f"отказ модели («{marker}») — в обучении не нужен")
                break
        if not CYR.search(answer):
            flags.append("ответ без русского текста")
        if MD_FENCE.search(answer):
            flags.append("ответ содержит markdown-разметку/списки — стоит нормализовать")

    visible = rec.get("visible_text") or ""
    precise: list[str] = []          # 22.09, 18.40 — такие числа модель читает с экрана
    round_: list[str] = []           # 25, 4 — часто нормативы/округления в тексте ответа
    if visible and answer:
        vis = _numbers(visible)
        for n in sorted(_numbers(answer)):
            if any(_close(n, v) for v in vis):
                continue
            (precise if "." in n else round_).append(n)
        if precise:
            flags.append("числа с дробной частью, которых не видно на экране "
                         f"(похоже на выдумку Gemini — проверить вручную): {', '.join(precise[:6])}")
        if round_:
            flags.append(f"круглые числа, которых нет на экране (обычно нормативы/округления): "
                         f"{', '.join(round_[:6])}")

    rec["qa"] = {
        "ok": not blocking and not precise,     # «круглые» числа — не повод выбрасывать пример
        "blocking": blocking,
        "flags": flags,
        "words": words,
        "numbers_in_answer": sorted(_numbers(answer)),
        "numbers_unverified": precise,
        "numbers_unverified_round": round_,
        "cluster_id": None,          # заполняется ниже (почти одинаковые кадры)
        "group": None,               # итоговая группа для сплитов
    }
    return rec


def _close(a: str, b: str, rel: float = 0.02, abs_tol: float = 0.05) -> bool:
    try:
        x, y = float(a), float(b)
    except ValueError:
        return a == b
    return abs(x - y) <= max(abs_tol, rel * max(abs(x), abs(y)))


def cluster_near_duplicates(records: list[dict], max_dist: int) -> int:
    """Почти одинаковые кадры → один cluster_id (простой union-find по dHash)."""
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    hashes = [r.get("dhash") or "" for r in records]
    for i in range(len(records)):
        if not hashes[i]:
            continue
        for j in range(i + 1, len(records)):
            if hashes[j] and pp.hamming(hashes[i], hashes[j]) <= max_dist:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(records)):
        groups.setdefault(find(i), []).append(i)
    for gi, (_, idxs) in enumerate(sorted(groups.items()), start=1):
        cid = f"cl_{gi:04d}"
        for i in idxs:
            records[i]["qa"]["cluster_id"] = cid
            records[i]["qa"]["cluster_size"] = len(idxs)
    return len(groups)


def assign_groups(records: list[dict], group_by: str) -> str:
    """Определяет итоговую группу для сплитов и возвращает, по какому признаку делили.

    Приоритет: метаданные о сессии (если они реально различают данные) → кластеры
    похожих кадров. Если метаданных нет и всё сваливается в одну папку, деление по
    «сессии» дало бы одну группу: train забрал бы всё, а val/test остались пустыми.
    Такие случаи автоматически уходят на деление по похожим кадрам.
    """
    total = len(records)
    sessions = [(r.get("session") or "").strip() for r in records]
    distinct = {s for s in sessions if s}
    biggest = max((sessions.count(s) for s in distinct), default=0)
    use_cluster = (group_by == "cluster" or not distinct
                   or len(distinct) < 3 or biggest > 0.6 * total)

    for r in records:
        if use_cluster:
            r["qa"]["group"] = r["qa"]["cluster_id"]
        else:
            r["qa"]["group"] = (r.get("session") or "").strip()
            if r["qa"].get("cluster_size", 1) > 1:
                r["qa"]["group"] = f"{r['qa']['group']}|{r['qa']['cluster_id']}"
    return "похожие кадры (метаданных о сессиях нет или они не различают данные)" if use_cluster \
        else "сессии из метаданных"


def main() -> None:
    ap = argparse.ArgumentParser(description="Контроль качества пар «скриншот + ответ»")
    ap.add_argument("--manifest", default="data/screens/manifest.jsonl")
    ap.add_argument("--out", default=None, help="куда записать отчёт (по умолчанию рядом с манифестом)")
    ap.add_argument("--report-name", default="qa_report.json")
    ap.add_argument("--strict", action="store_true", help="вернуть код 1, если есть блокирующие проблемы")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/vision.yaml")
    manifest = common.ROOT / args.manifest
    if not manifest.exists():
        print(f"Нет манифеста {args.manifest}. Сначала: python -m src.dataset.import_screenshots --src <папка>")
        return

    records = common.read_jsonl(manifest)
    records = [review(r, cfg) for r in records]
    clusters = cluster_near_duplicates(records, cfg["splits"]["near_duplicate_hamming"])
    group_basis = assign_groups(records, cfg["splits"]["group_by"])

    blocking = [r for r in records if r["qa"]["blocking"]]
    warned = [r for r in records if r["qa"]["flags"] and not r["qa"]["blocking"]]
    clean = [r for r in records if r["qa"]["ok"]]
    dupes = [r for r in records if r["qa"].get("cluster_size", 1) > 1]
    unverified = [r for r in records if r["qa"]["numbers_unverified"]]

    common.write_jsonl(manifest, records)
    out = Path(args.out) if args.out else manifest.parent / args.report_name
    report = {
        "manifest": args.manifest,
        "screens": len(records),
        "ok": len(clean), "warnings": len(warned), "blocking": len(blocking),
        "clusters": clusters, "in_clusters": len(dupes),
        "groups": len({r["qa"]["group"] for r in records}),
        "group_basis": group_basis,
        "with_unverified_numbers": len(unverified),
        "blocking_examples": [{"id": r["id"], "why": r["qa"]["blocking"]} for r in blocking[:20]],
        "flagged_examples": [{"id": r["id"], "flags": r["qa"]["flags"]} for r in warned[:20]],
    }
    common.write_json(out, report)

    print("=" * 78)
    print(f"КОНТРОЛЬ КАЧЕСТВА ДАТАСЕТА · {args.manifest}")
    print("=" * 78)
    print(f"  скриншотов:                 {len(records)}")
    print(f"  чистых:                     {len(clean)}")
    print(f"  с замечаниями:              {len(warned)}")
    print(f"  блокирующих (в обучение нельзя): {len(blocking)}")
    print(f"  кластеров похожих кадров:   {clusters}  (в них {len(dupes)} скриншотов)")
    print(f"  групп для сплитов:          {report['groups']} ({group_basis})")
    print(f"  ответов с неподтверждёнными числами: {len(unverified)}")
    for r in blocking[:6]:
        print(f"    ✗ {r['id']}: {', '.join(r['qa']['blocking'])}")
    for r in warned[:6]:
        print(f"    ! {r['id']}: {', '.join(r['qa']['flags'][:2])}")
    print(f"\n  отчёт: {common.rel_to_root(out)}")
    print("\nДальше:  python -m src.dataset.build_vl_dataset")

    if args.strict and blocking:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
