"""Проверка «чистоты» данных: в датасете обучения не должно быть синтетики.

Смысл правила: обучаемся только на реальных данных — моделях и разметке инженеров.
Синтетика (автотест конвейера, демо-примеры) допустима в тестах и в аугментации,
которую вы делаете осознанно. Этот скрипт показывает, что реально лежит в рабочих папках.

Запуск:
    python tools/check_data_purity.py
    python tools/check_data_purity.py --dir data/cases/filled
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import common     # noqa: E402
from src.dataset.export_instruct import _is_synthetic     # noqa: E402

DEFAULT_DIRS = ["data/cases/filled", "data/collected/cases", "data/splits"]


def scan_cases(directory: Path) -> dict:
    files = sorted(directory.glob("c_*.json")) + sorted(directory.glob("*.json"))
    files = [f for f in files if f.name not in ("manifest.json",)]
    real, synthetic, sources, annotators = [], [], Counter(), Counter()
    for fp in files:
        try:
            case = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if "case_id" not in case:
            continue
        ann = case.get("annotation") or {}
        sources[ann.get("source") or "—"] += 1
        annotators[ann.get("annotator_id") or "—"] += 1
        (synthetic if _is_synthetic(case) else real).append(fp.name)
    return {"dir": str(directory.relative_to(common.ROOT)) if directory.is_relative_to(common.ROOT) else str(directory),
            "total": len(real) + len(synthetic), "real": len(real), "synthetic": len(synthetic),
            "synthetic_files": synthetic[:10], "sources": dict(sources), "annotators": dict(annotators)}


def scan_splits(path: Path) -> dict:
    if not path.exists():
        return {"file": str(path), "rows": 0, "synthetic": 0}
    rows = common.read_jsonl(path)
    synth = [r for r in rows if (r.get("meta") or {}).get("synthetic")]
    return {"file": name(path), "rows": len(rows), "synthetic": len(synth)}


def name(p: Path) -> str:
    try:
        return str(p.relative_to(common.ROOT))
    except ValueError:
        return str(p)


def main() -> None:
    ap = argparse.ArgumentParser(description="Чистота данных: есть ли синтетика в датасете")
    ap.add_argument("--dir", action="append", default=None,
                    help="каталог с кейсами (можно несколько раз; по умолчанию рабочие каталоги)")
    args = ap.parse_args()

    dirs = [common.ROOT / d for d in (args.dir or DEFAULT_DIRS)]
    print("=" * 78)
    print("ПРОВЕРКА ЧИСТОТЫ ДАННЫХ · правило: только реальные данные")
    print("=" * 78)

    total_real = total_synth = 0
    for d in dirs:
        if not d.exists():
            print(f"\n{d.relative_to(common.ROOT)}: каталога нет")
            continue
        if d.is_file() or d.suffix == ".jsonl":
            info = scan_splits(d)
            print(f"\n{info['file']}: строк {info['rows']}, синтетических {info['synthetic']}")
            total_synth += info["synthetic"]
            continue
        if d.is_dir() and "splits" in d.name:
            files = sorted(d.glob("*.jsonl"))
            if not files:
                print(f"\n{d.relative_to(common.ROOT)}: файлов датасета нет (пусто — это нормально)")
                continue
            for f in files:
                info = scan_splits(f)
                print(f"  {info['file']}: строк {info['rows']}, синтетических {info['synthetic']}")
                total_synth += info["synthetic"]
            continue
        info = scan_cases(d)
        total_real += info["real"]
        total_synth += info["synthetic"]
        print(f"\n{info['dir']}: кейсов {info['total']} "
              f"(реальных {info['real']}, синтетических {info['synthetic']})")
        if info["sources"]:
            print("  источники:", info["sources"])
        if info["annotators"]:
            print("  разметили:", info["annotators"])
        if info["synthetic"]:
            print("  ⚠ синтетические файлы:", ", ".join(info["synthetic_files"]))

    # сплиты обучения
    for f in ("data/splits/train.jsonl", "data/splits/val.jsonl", "data/splits/test.jsonl",
              "data/splits/structured.jsonl", "data/splits/eval_test.jsonl"):
        info = scan_splits(common.ROOT / f)
        if info["rows"]:
            print(f"{info['file']}: строк {info['rows']}")

    print("\n" + "-" * 78)
    if total_real == 0 and total_synth == 0:
        print("Данных пока нет — это нормальное состояние чистого репозитория.")
        print("Наполнение: разметка через сервис (docs/10) или data/cases/filled для внутренней разметки.")
    elif total_synth:
        print(f"ВНИМАНИЕ: найдено синтетических кейсов: {total_synth}. "
              f"Они не попадут в обучение (export_instruct их пропускает), но лучше удалить.")
    else:
        print(f"Чисто: реальных кейсов {total_real}, синтетики нет. Можно обучаться.")
    print("Тестовые фикстуры лежат отдельно и в датасет не попадают: tests/fixtures/")


if __name__ == "__main__":
    main()
