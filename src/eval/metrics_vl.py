"""Оценка локальной модели на скриншотах: «насколько её ответ похож на золотой».

Мы не можем судить «правильно/неправильно» по одному взгляду, поэтому считаем
набор проверяемых величин, каждая из которых ловит свой тип ошибки:

  numbers_f1       — совпадение чисел с эталоном Gemini (с допуском 2 %)
  ids_f1           — совпадение ID объектов (J105, P-106, R-1)
  meaning_f1       — пересечение значимых слов (о чём вообще ответ)
  grounding_rate   — доля чисел ответа, которые реально видно на экране (по OCR)
  hallucinated_rate— доля чисел ответа, которых на экране нет (выдумка)
  refusal_rate     — доля ответов-отказов («не могу определить»)
  length_ok_rate   — доля ответов разумной длины

Можно сравнивать несколько наборов ответов на одной и той же отложенной выборке:
например, `gemini` (эталон), `base` (модель до обучения) и `ours` (после).
Так видно и абсолютное качество, и эффект обучения.

Запуск:
    python -m src.eval.metrics_vl --ref data/screens/eval_reference.jsonl \
        --pred base=outputs/base_pred.jsonl --pred ours=outputs/ours_pred.jsonl

Формат предсказаний (JSONL): {"id": "scr_01", "answer": "..."} — поле ответа может
называться answer / prediction / output / response.
"""
from __future__ import annotations

import argparse
import re
import statistics
from pathlib import Path

from .. import common

NUM = re.compile(r"\d+(?:[.,]\d+)?")
ID = re.compile(r"\b[А-ЯA-Z]{1,3}[-–]?\d{1,4}\b")
STOP = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все", "она",
    "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "ее",
    "мне", "было", "вот", "от", "меня", "еще", "нет", "о", "из", "ему", "теперь", "когда",
    "даже", "ну", "вдруг", "ли", "если", "уже", "или", "ни", "быть", "был", "него", "до",
    "вас", "нибудь", "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем",
    "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже", "себе", "под", "будет",
    "ж", "тогда", "кто", "этот", "того", "потому", "этого", "какой", "совсем", "ним",
    "здесь", "этом", "один", "почти", "мой", "тем", "чтобы", "нее", "сейчас", "были",
    "куда", "зачем", "всех", "никогда", "можно", "при", "наконец", "два", "об", "другой",
    "хоть", "после", "над", "больше", "тот", "через", "эти", "нас", "про", "всего", "них",
    "какая", "много", "разве", "три", "эту", "моя", "впрочем", "хорошо", "свою", "этой",
    "перед", "иногда", "лучше", "чуть", "том", "нельзя", "такой", "им", "более", "всегда",
    "конечно", "всю", "между", "the", "a", "an", "of", "and", "or", "to", "in", "is", "are",
}


def _nums(text: str) -> list[float]:
    out = []
    for m in NUM.finditer(text or ""):
        try:
            out.append(float(m.group(0).replace(",", ".")))
        except ValueError:
            pass
    return out


def _ids(text: str) -> set[str]:
    return {m.group(0).upper().replace("–", "-") for m in ID.finditer(text or "")}


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[а-яёa-z]{4,}", (text or "").lower())
    return {w[:6] for w in words if w not in STOP}


def _f1(matched: int, n_pred: int, n_gold: int) -> float:
    """F1 по числу совпавших элементов. Если эталон пуст и ответ пуст — 1.0,
    если эталон непуст, а ответ нет — 0.0 (частый случай «стёрли все числа»)."""
    if n_pred == 0 and n_gold == 0:
        return 1.0
    if n_pred == 0 or n_gold == 0:
        return 0.0
    p = matched / n_pred
    r = matched / n_gold
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def _match_numbers(pred: list[float], gold: list[float],
                   rel: float = 0.02, abs_tol: float = 0.05) -> int:
    """Сколько чисел ответа удалось сопоставить с эталоном (с допуском 2 %).

    Именно КОЛИЧЕСТВО, а не множество: «4» может встретиться в тексте несколько
    раз, и каждое вхождение — отдельное попадание.
    """
    used = [False] * len(gold)
    matched = 0
    for pv in pred:
        best, best_d = None, None
        for i, gv in enumerate(gold):
            if used[i]:
                continue
            d = abs(pv - gv) / max(abs(gv), 1e-9)
            if abs(pv - gv) <= max(abs_tol, rel * max(abs(pv), abs(gv))) and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is not None:
            used[best] = True
            matched += 1
    return matched


def _is_refusal(text: str, cfg: dict) -> bool:
    low = (text or "").lower()
    return any(m in low for m in cfg["quality"]["refusal_markers"])


def load_predictions(path: Path) -> dict[str, str]:
    rows = common.read_jsonl(path)
    out: dict[str, str] = {}
    for r in rows:
        cid = r.get("id") or r.get("case_id") or r.get("image") or r.get("image_id")
        ans = r.get("answer") or r.get("prediction") or r.get("output") or r.get("response") or ""
        if cid:
            out[Path(str(cid)).stem] = str(ans).strip()
    return out


def score_set(ref: list[dict], preds: dict[str, str], cfg: dict, use_visible: bool) -> tuple[dict, list[dict]]:
    numbers_f1, ids_f1, meaning_f1 = [], [], []
    grounded, hallucinated, refusals, length_ok, missing = [], [], [], [], 0
    per_item: list[dict] = []

    for item in ref:
        gold = item.get("answer", "")
        pred = preds.get(item["id"])
        if pred is None:
            missing += 1
            continue
        pv, gv = _nums(pred), _nums(gold)
        nf = _f1(_match_numbers(pv, gv), len(pv), len(gv))
        pids, gids = _ids(pred), _ids(gold)
        idf = _f1(len(pids & gids), len(pids), len(gids))
        pw, gw = _content_words(pred), _content_words(gold)
        mf = _f1(len(pw & gw), len(pw), len(gw))
        numbers_f1.append(nf); ids_f1.append(idf); meaning_f1.append(mf)

        visible = item.get("visible_text") or ""
        vis = _nums(visible)
        if use_visible and vis:
            # проверяем только точные числа (22.09): круглые (25, 46) — это нормативы,
            # пороги и округления, их отсутствие на экране не ошибка
            precise = [v for v in pv if abs(v - round(v)) > 1e-9]
            good = sum(1 for v in precise
                       if any(abs(v - s) <= max(0.05, 0.02 * max(abs(v), abs(s))) for s in vis))
            grounded.append(good / len(precise) if precise else 1.0)
            hallucinated.append((len(precise) - good) / len(precise) if precise else 0.0)
        refusals.append(1.0 if _is_refusal(pred, cfg) else 0.0)
        w = len(pred.split())
        length_ok.append(1.0 if cfg["quality"]["min_answer_words"] <= w <= cfg["quality"]["max_answer_words"] else 0.0)
        per_item.append({"id": item["id"], "numbers_f1": round(nf, 3), "ids_f1": round(idf, 3),
                         "meaning_f1": round(mf, 3), "words": w,
                         "refusal": bool(refusals[-1]),
                         "ungrounded_numbers": [v for v in pv
                                                if vis and abs(v - round(v)) > 1e-9
                                                and not any(abs(v - s) <= max(0.05, 0.02 * max(abs(v), abs(s)))
                                                            for s in vis)]})

    def mean(xs: list[float]) -> float:
        return round(statistics.fmean(xs), 4) if xs else 0.0

    metrics = {
        "n": len([i for i in ref if i["id"] in preds]),
        "missing": missing,
        "numbers_f1": mean(numbers_f1),
        "ids_f1": mean(ids_f1),
        "meaning_f1": mean(meaning_f1),
        "grounding_rate": mean(grounded),
        "hallucinated_number_rate": mean(hallucinated),
        "refusal_rate": mean(refusals),
        "length_ok_rate": mean(length_ok),
    }
    return metrics, per_item


def main() -> None:
    ap = argparse.ArgumentParser(description="Метрики локальной модели на скриншотах")
    ap.add_argument("--ref", default="data/screens/eval_reference.jsonl",
                    help="эталон: скриншоты + золотые ответы (тестовая часть датасета)")
    ap.add_argument("--pred", action="append", default=[], metavar="ИМЯ=ФАЙЛ.jsonl",
                    help="набор предсказаний; можно указывать несколько раз")
    ap.add_argument("--out", default="data/eval/vl_metrics.json")
    ap.add_argument("--no-visible-check", action="store_true",
                    help="не проверять числа по тексту экрана (если OCR нет)")
    args = ap.parse_args()

    cfg = common.load_yaml("configs/vision.yaml")
    ref_path = common.ROOT / args.ref
    if not ref_path.exists() or not common.read_jsonl(ref_path):
        print("=" * 78)
        print("ОЦЕНКА VLM: пока нечего оценивать")
        print("=" * 78)
        print(f"  Нет отложенной выборки {args.ref}.")
        print("  Порядок: датасет заказчика → data/screens/raw → import_screenshots →")
        print("           check_screenshot_pairs → build_vl_dataset (создаст eval_reference.jsonl)")
        return
    ref = common.read_jsonl(ref_path)

    if not args.pred:
        print(f"Эталон на месте: {len(ref)} скриншотов в {args.ref}")
        print("Передайте предсказания: --pred ours=outputs/ours_pred.jsonl")
        return

    results: dict[str, dict] = {}
    details: dict[str, list] = {}
    for spec in args.pred:
        if "=" not in spec:
            print(f"! пропускаю {spec}: ожидается формат ИМЯ=ФАЙЛ.jsonl")
            continue
        name, path = spec.split("=", 1)
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = common.ROOT / p
        if not p.exists():
            print(f"! нет файла предсказаний: {p}")
            continue
        metrics, per_item = score_set(ref, load_predictions(p), cfg, not args.no_visible_check)
        results[name] = metrics
        details[name] = per_item

    if not results:
        print("Ничего не оценено.")
        return

    thr = cfg["eval"]["thresholds"]
    print("=" * 78)
    print(f"ОЦЕНКА НА СКРИНШОТАХ · отложенная выборка {len(ref)} шт")
    print("=" * 78)
    cols = ["numbers_f1", "ids_f1", "meaning_f1", "grounding_rate", "hallucinated_number_rate",
            "refusal_rate", "length_ok_rate"]
    head = f"  {'набор':<14}" + "".join(f"{c[:14]:>16}" for c in cols)
    print(head)
    for name, m in results.items():
        row = f"  {name:<14}" + "".join(f"{m[c]:>16.3f}" for c in cols)
        print(row)
    print(f"\n  пороги: numbers_f1 ≥ {thr['numbers_f1']}, ids_f1 ≥ {thr['ids_f1']}, "
          f"grounding ≥ {thr['grounding_rate']}, выдуманные числа ≤ {thr['hallucinated_number_rate']}, "
          f"отказы ≤ {thr['refusal_rate']}")

    verdict: dict[str, list[str]] = {}
    for name, m in results.items():
        bad = []
        if m["numbers_f1"] < thr["numbers_f1"]:
            bad.append(f"числа {m['numbers_f1']:.2f} < {thr['numbers_f1']}")
        if m["ids_f1"] < thr["ids_f1"]:
            bad.append(f"ID объектов {m['ids_f1']:.2f} < {thr['ids_f1']}")
        if m["grounding_rate"] and m["grounding_rate"] < thr["grounding_rate"]:
            bad.append(f"подтверждение чисел экраном {m['grounding_rate']:.2f} < {thr['grounding_rate']}")
        if m["hallucinated_number_rate"] > thr["hallucinated_number_rate"]:
            bad.append(f"выдуманные числа {m['hallucinated_number_rate']:.2f} > {thr['hallucinated_number_rate']}")
        if m["refusal_rate"] > thr["refusal_rate"]:
            bad.append(f"отказы {m['refusal_rate']:.2f} > {thr['refusal_rate']}")
        verdict[name] = bad
        print(f"  {'✓' if not bad else '✗'} {name}: " + ("пороги пройдены" if not bad else "; ".join(bad)))

    if "ours" in results and "base" in results:
        d = results["ours"]["numbers_f1"] - results["base"]["numbers_f1"]
        print(f"\n  эффект обучения (ours − base) по числам: {d:+.3f}")

    out = common.ensure_dir(common.ROOT / Path(args.out).parent) / Path(args.out).name
    common.write_json(out, {"ref": args.ref, "n_ref": len(ref), "thresholds": thr,
                            "metrics": results, "verdict": verdict, "per_item": details})
    print(f"\n  отчёт: {common.rel_to_root(out)}")

    worst = sorted(details.get("ours", details[list(details)[0]]), key=lambda r: r["numbers_f1"])[:5]
    if worst:
        print("  худшие по числам (посмотреть глазами):")
        for r in worst:
            extra = f", лишние числа {r['ungrounded_numbers'][:3]}" if r["ungrounded_numbers"] else ""
            print(f"    {r['id']}: numbers_f1={r['numbers_f1']}, слов {r['words']}{extra}")


if __name__ == "__main__":
    main()
