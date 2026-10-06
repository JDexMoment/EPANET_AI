"""Оценка подсистемы «понимание экрана» (без обучения — только измерения).

Сравнивает разметку скриншотов (data/screen_labels/**) с результатами detect_screen.
Метрики подобраны под реальный риск: опасен не «не распознал», а «молча выбрал
НЕ ТОТ объект» — поэтому wrong_object_rate и abstention считаются отдельно.

Запуск:
    python -m src.eval.metrics_screen \
        --labels tests/fixtures/screen_demo \
        --pred tests/fixtures/screen_demo/predictions.jsonl \
        --out data/eval/screen_scores.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import common     # noqa: E402


def _obj_id(rec) -> str | None:
    if not rec:
        return None
    return rec.get("id") if isinstance(rec, dict) else str(rec)


def _values(rec: dict) -> dict:
    return {v["id"]: round(float(v["value"]), 2) for v in rec.get("visible_objects", [])
            if v.get("value") is not None}


def _actions(rec: dict) -> set[str]:
    """Разметка может хранить действия строками («focus_entity»), детектор — объектами."""
    out = set()
    for a in rec.get("actions", []) or []:
        out.add(a["intent"] if isinstance(a, dict) else str(a))
    return out


def evaluate(labels: list[dict], preds: dict[str, dict]) -> dict:
    n = len(labels)
    st_ok = objs = obj_ok = wrong_obj = vt = val_ok = ts = ts_ok = 0
    act_tp = act_fp = act_fn = 0
    amb_total = amb_ok = 0
    lat, ram = [], []

    for lab in labels:
        gold = lab.get("golden", lab)
        sid = lab.get("screen_id")
        pred = preds.get(sid)
        if not pred:
            continue
        if pred.get("screen_type") == gold.get("screen_type"):
            st_ok += 1

        g_obj, p_obj = _obj_id(gold.get("selected_object")), _obj_id(pred.get("selected_object"))
        if g_obj or p_obj:
            objs += 1
            if g_obj == p_obj:
                obj_ok += 1
            elif p_obj is not None:
                wrong_obj += 1

        g_val, p_val = _values(gold), _values(pred)
        if g_val:
            vt += 1
            if all(p_val.get(k) == v for k, v in g_val.items()):
                val_ok += 1

        g_ts = (gold.get("timestep") or {}).get("hour")
        p_ts = (pred.get("timestep") or {}).get("hour")
        if g_ts is not None or p_ts is not None:
            ts += 1
            if (g_ts is None and p_ts is None) or (g_ts is not None and p_ts is not None
                                                   and abs(g_ts - p_ts) <= 1):
                ts_ok += 1

        ga, pa = _actions(gold), _actions(pred)
        act_tp += len(ga & pa)
        act_fp += len(pa - ga)
        act_fn += len(ga - pa)

        g_amb = (gold.get("ambiguity") or {}).get("level")
        if g_amb in ("medium", "high"):
            amb_total += 1
            p_amb = (pred.get("ambiguity") or {}).get("level")
            if p_amb in ("medium", "high") or _obj_id(pred.get("selected_object")) is None:
                amb_ok += 1

        if pred.get("latency_ms") is not None:
            lat.append(float(pred["latency_ms"]))
        if pred.get("peak_ram_mb") is not None:
            ram.append(float(pred["peak_ram_mb"]))

    prec = act_tp / (act_tp + act_fp) if (act_tp + act_fp) else 0.0
    rec = act_tp / (act_tp + act_fn) if (act_tp + act_fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    def frac(a, b):
        return round(a / b, 4) if b else None

    lat_sorted = sorted(lat)
    return {
        "screens": n,
        "screens_scored": sum(1 for lab in labels if lab.get("screen_id") in preds),
        "screen_type_accuracy": frac(st_ok, n),
        "selected_object_accuracy": frac(obj_ok, objs),
        "wrong_object_rate": frac(wrong_obj, objs),
        "value_binding_accuracy": frac(val_ok, vt),
        "timestep_accuracy": frac(ts_ok, ts),
        "action_precision": round(prec, 4),
        "action_recall": round(rec, 4),
        "action_f1": round(f1, 4),
        "abstention_rate_on_ambiguous": frac(amb_ok, amb_total),
        "latency_ms_mean": round(sum(lat) / len(lat), 1) if lat else None,
        "latency_ms_p95": lat_sorted[int(0.95 * (len(lat_sorted) - 1))] if lat_sorted else None,
        "peak_ram_mb_max": max(ram) if ram else None,
    }


def verdict(m: dict, acc: dict) -> list[str]:
    checks = [
        ("screen_type_accuracy", m["screen_type_accuracy"], acc["screen_type_accuracy"], "min"),
        ("selected_object_accuracy", m["selected_object_accuracy"], acc["selected_object_accuracy"], "min"),
        ("wrong_object_rate", m["wrong_object_rate"], acc["wrong_object_rate_max"], "max"),
        ("value_binding_accuracy", m["value_binding_accuracy"], acc["value_binding_accuracy"], "min"),
        ("timestep_accuracy", m["timestep_accuracy"], acc["timestep_accuracy"], "min"),
        ("action_f1", m["action_f1"], acc["action_f1"], "min"),
        ("abstention_rate_on_ambiguous", m["abstention_rate_on_ambiguous"],
         acc["abstention_rate_on_ambiguous"], "min"),
    ]
    lines = []
    for name, val, thr, kind in checks:
        if val is None:
            lines.append(f"   {name:32s} —            (нет данных)")
            continue
        ok = val >= thr if kind == "min" else val <= thr
        mark = "OK " if ok else "НЕТ"
        op = "≥" if kind == "min" else "≤"
        lines.append(f"   [{mark}] {name:28s} {val:<8} (норма {op} {thr})")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Метрики понимания экрана")
    ap.add_argument("--labels", default="data/screen_labels")
    ap.add_argument("--pred", default=None, help="JSONL с предсказаниями (по умолчанию <labels>/predictions.jsonl)")
    ap.add_argument("--out", default="data/eval/screen_scores.json")
    args = ap.parse_args()

    labels_dir = common.ROOT / args.labels
    pred_path = common.ROOT / args.pred if args.pred else labels_dir / "predictions.jsonl"
    if not pred_path.exists():
        print(f"Нет файла предсказаний {pred_path}")
        print("Сначала: python -m src.vision.detect_screen --image ... --out ..., затем собрать JSONL.")
        return

    labels = []
    for fp in sorted(labels_dir.glob("*.json")):
        if fp.name == "predictions.jsonl":
            continue
        rec = json.loads(fp.read_text(encoding="utf-8"))
        if "golden" in rec and rec.get("screen_id"):
            labels.append(rec)
    if not labels:
        print(f"В {labels_dir} нет размеченных экранов (нужны файлы с полями screen_id и golden).")
        print("Разметка: откройте tools/label_screen.html и экспортируйте JSON в data/screen_labels/.")
        return

    preds = {}
    for row in common.read_jsonl(pred_path):
        preds[row["screen_id"]] = row

    metrics = evaluate(labels, preds)
    acc = common.load_yaml("configs/ui.yaml")["acceptance"]

    print("=" * 78)
    print("ПОНИМАНИЕ ЭКРАНА (screen understanding)")
    print("=" * 78)
    print(f" размечено экранов: {metrics['screens']}, оценено: {metrics['screens_scored']}")
    if labels_dir.name == "demo":
        print(" ВНИМАНИЕ: это демо-набор (синтетические OCR-блоки), а не бенчмарк на реальных скриншотах.")
    for line in verdict(metrics, acc):
        print(line)

    out = common.ROOT / args.out
    common.ensure_dir(out.parent)
    out.write_text(json.dumps({"metrics": metrics, "acceptance": acc}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
