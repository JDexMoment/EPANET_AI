"""Сборка датасета обучения для VLM: сплиты train/val/test + форматы тренеров.

Деление — ПО ГРУППАМ (сессия / кластер похожих кадров), а не по картинкам: иначе
почти одинаковые скриншоты одной сессии попадают и в train, и в test, и метрики
показывают красивую неправду.

На выходе (по умолчанию в data/screens/):
  dataset.jsonl              — канонический вид: id, group, image, question, answer
  swift_{train,val,test}.jsonl     — формат ms-swift: {"messages":[…], "images":[…]}
  sharegpt_{train,val,test}.jsonl  — тот же вид, что ждёт LLaMA-Factory
  eval_reference.jsonl       — тестовая часть с «золотыми» ответами для метрик

Дополнительно: --copy-images складывает рабочие копии картинок в out/images
(с приведением к безопасному размеру), чтобы датасет был самодостаточным.

Запуск:
    python -m src.dataset.build_vl_dataset
    python -m src.dataset.build_vl_dataset --copy-images --min-qa clean
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

from .. import common
from ..vision import preprocess as pp


def _h(group: str) -> int:
    return int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16)


def split_groups(records: list[dict], ratios: dict) -> dict[str, str]:
    """Детерминированно распределяет ГРУППЫ по train/val/test, попадая в пропорции.

    Чистый хеш при десятках групп нередко сваливает всё в train — поэтому группы
    сортируются по хешу (порядок стабильный и не зависит от порядка файлов) и
    раскидываются так, чтобы попасть в целевые доли по количеству примеров.
    """
    by_group: dict[str, int] = {}
    for r in records:
        by_group[r["qa"]["group"]] = by_group.get(r["qa"]["group"], 0) + 1
    total = sum(by_group.values())
    target = {"train": total * ratios["train"], "val": total * ratios["val"],
              "test": total * ratios["test"]}
    got = {"train": 0, "val": 0, "test": 0}
    order = sorted(by_group, key=_h)
    assign: dict[str, str] = {}
    for g in order:
        n = by_group[g]
        # берём выборку, где сильнее недобор относительно цели
        best = max(("val", "test", "train"), key=lambda b: target[b] - got[b])
        if got[best] + n > target[best] * 1.35 and got[best] > 0:
            best = max(("train", "val", "test"), key=lambda b: target[b] - got[b])
        assign[g] = best
        got[best] += n
    # гарантируем непустые val и test: иначе на малых датасетах метрики вообще не посчитать.
    # переносим в val/test самые маленькие группы, но train всегда оставляем с большинством
    if total >= 5 and len(by_group) >= 3:
        for bucket in ("val", "test"):
            if got[bucket] > 0:
                continue
            for g in sorted(order, key=lambda g: by_group[g]):
                if assign[g] != "train":
                    continue
                if got["train"] - by_group[g] >= max(1, int(total * 0.5)):
                    got["train"] -= by_group[g]
                    assign[g] = bucket
                    got[bucket] += by_group[g]
                    break
    return assign


def _record(rec: dict, image_path: str) -> dict:
    return {"id": rec["id"], "group": rec["qa"]["group"], "image": image_path,
            "question": rec["question"], "answer": rec["answer"].strip(),
            "visible_text": rec.get("visible_text") or "",
            "meta": {"session": rec.get("session"), "width": rec.get("width"),
                     "height": rec.get("height"), "cluster": rec["qa"]["cluster_id"],
                     "flags": rec["qa"]["flags"]}}


def _messages(rec: dict) -> list[dict]:
    return [
        {"role": "user", "content": f"<image>\n{rec['question']}"},
        {"role": "assistant", "content": rec["answer"]},
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Сборка датасета для обучения VLM")
    ap.add_argument("--manifest", default="data/screens/manifest.jsonl")
    ap.add_argument("--out", default="data/screens")
    ap.add_argument("--min-qa", choices=["clean", "warnings", "all"], default="warnings",
                    help="кого брать в обучение: только чистых, без блокирующих проблем (по умолчанию), "
                         "или вообще всех. Блокирующие (отказы, пустые ответы) не берутся никогда")
    ap.add_argument("--copy-images", action="store_true",
                    help="сложить рабочие копии картинок в out/images (самодостаточный датасет)")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/vision.yaml")
    ratios = cfg["splits"]["ratios"]
    manifest = common.ROOT / args.manifest
    if not manifest.exists():
        print(f"Нет манифеста {args.manifest}. Сначала: import_screenshots → check_screenshot_pairs")
        return

    records = common.read_jsonl(manifest)
    if not records:
        print("Манифест пуст.")
        return
    if not any(r.get("qa") for r in records):
        print("В манифесте нет результатов проверки. Сначала: python -m src.dataset.check_screenshot_pairs")
        return

    def keep(r: dict) -> bool:
        qa = r["qa"]
        if qa["blocking"]:
            return False
        if args.min_qa == "clean":
            return qa["ok"]
        return True

    selected = [r for r in records if keep(r)]
    dropped = len(records) - len(selected)

    out_dir = common.ensure_dir(common.ROOT / args.out)
    img_dir = None
    if args.copy_images:
        img_dir = common.ensure_dir(out_dir / "images")

    group_bucket = split_groups(selected, ratios)
    buckets: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for rec in selected:
        src_img = Path(rec.get("image_abs") or rec["image"])
        image_ref = rec["image"]
        if img_dir is not None:
            dst = img_dir / f"{rec['id']}.png"
            if not dst.exists():
                pp.prepare_image(src_img, dst, cfg["images"]["max_pixels"],
                                 cfg["images"]["max_side"], cfg["images"]["min_side"])
            image_ref = common.rel_to_root(dst)
        buckets[group_bucket[rec["qa"]["group"]]].append(_record(rec, image_ref))

    if not any(buckets.values()):
        print("После фильтрации не осталось данных — проверьте отчёт контроля качества.")
        return

    canon: dict[str, list[dict]] = {}
    for name, rows in buckets.items():
        canon[name] = rows
        common.write_jsonl(out_dir / f"{name}.jsonl", rows)
        common.write_jsonl(out_dir / f"swift_{name}.jsonl",
                           [{"messages": _messages(r), "images": [r["image"]]} for r in rows])
        common.write_jsonl(out_dir / f"sharegpt_{name}.jsonl",
                           [{"messages": _messages(r), "images": [r["image"]]} for r in rows])
    common.write_jsonl(out_dir / "dataset.jsonl", [r for rows in canon.values() for r in rows])
    common.write_jsonl(out_dir / "eval_reference.jsonl", canon["test"])

    print("=" * 78)
    print("СБОРКА ДАТАСЕТА ДЛЯ VLM (скриншоты → ответ)")
    print("=" * 78)
    print(f"  взято в датасет:      {len(selected)} из {len(records)}  (отсеяно: {dropped})")
    print(f"  фильтр:               {args.min_qa}")
    for name in ("train", "val", "test"):
        print(f"  {name:<20} {len(canon[name]):>4} примеров, групп: {len({r['group'] for r in canon[name]})}")
    print(f"  каталог:              {common.rel_to_root(out_dir)}")
    if img_dir:
        size = sum(f.stat().st_size for f in img_dir.glob('*'))
        print(f"  рабочие копии картинок: {len(list(img_dir.glob('*')))} шт, {common.human_size(size)}")
    if len(canon["val"]) < 8 or len(canon["test"]) < 8:
        print("  ! val/test малы: для честных метрик нужно ≥ 30-50 скриншотов на выборку,")
        print("    при малом датасете метрики шумят — судите по нескольким прогонам.")
    print("\nДальше:  python -m src.train.vl_lora --print-plan   (план обучения под эту машину)")

    if not selected:
        return
    steps = len(selected)
    print(f"\nОриентир по обучению: ~{steps} картинок, 2 эпохи ⇒ "
          f"{steps * 2 // max(1, cfg['training']['gradient_accumulation_steps'])} шагов оптимизации.")


if __name__ == "__main__":
    main()
