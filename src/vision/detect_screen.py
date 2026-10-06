"""Понимание экрана: скриншот → структурированный JSON (без CV/VLM-модели).

Стек: OCR (RapidOCR / PaddleOCR / Tesseract) + геометрия текстовых блоков +
словари и шаблоны из configs/ui.yaml. Опционально сверка найденных ID с сетью (.inp).

Запуск:
    # 1) скриншот
    python -m src.vision.detect_screen --image screenshots/map_j105.png \
        --inp tests/fixtures/networks/vn01_demo.inp --out /tmp/screen_map_j105.json
    # 2) офлайн-режим: готовые OCR-блоки (JSON) — тесты, демо, обмен с разработчиком
    python -m src.vision.detect_screen --ocr-blocks tests/fixtures/screen_demo/ocr_01.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import common                      # noqa: E402
from src.vision import schema               # noqa: E402


# ─────────────────────────────── конфигурация
def load_cfg() -> dict:
    return common.load_yaml("configs/ui.yaml")


def compile_patterns(cfg: dict) -> dict:
    p = cfg["patterns"]
    return {
        "node": [re.compile(r, re.I) for r in p["node_ids"]],
        "link": [re.compile(r, re.I) for r in p["link_ids"]],
        "timestep": [re.compile(r, re.I) for r in p["timestep"]],
        "number": re.compile(p["number"]),
        "units": [(re.compile(u["regex"], re.I), u["unit"], u["metric"]) for u in p["units"]],
    }


def known_ids_from_inp(path: str | Path | None) -> set[str] | None:
    if not path:
        return None
    try:
        import wntr
        wn = wntr.network.WaterNetworkModel(str(path))
        return set(wn.node_name_list) | set(wn.link_name_list)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] не удалось прочитать сеть {path}: {e}")
        return None


# ─────────────────────────────── OCR
def _box_to_block(box, text: str, conf: float) -> dict:
    xs = [float(pt[0]) for pt in box]
    ys = [float(pt[1]) for pt in box]
    return {"text": str(text).strip(), "x": int(min(xs)), "y": int(min(ys)),
            "w": int(max(xs) - min(xs)), "h": int(max(ys) - min(ys)), "conf": round(float(conf), 3)}


def _ocr_rapidocr(path: Path):
    from rapidocr_onnxruntime import RapidOCR          # type: ignore
    engine = RapidOCR()
    res, _ = engine(str(path))
    blocks = [_box_to_block(item[0], item[1], item[2]) for item in (res or [])]
    return blocks, "rapidocr"


def _ocr_paddleocr(path: Path):
    from paddleocr import PaddleOCR                     # type: ignore
    ocr = PaddleOCR(use_angle_cls=True, lang="ru", show_log=False)
    res = ocr.ocr(str(path), cls=True)
    lines = (res[0] if res and isinstance(res[0], list) else res) or []
    blocks = [_box_to_block(item[0], item[1][0], item[1][1]) for item in lines]
    return blocks, "paddleocr"


def _ocr_pytesseract(path: Path, lang: str):
    import pytesseract                                   # type: ignore
    from PIL import Image                                # type: ignore
    data = pytesseract.image_to_data(Image.open(path), lang=lang,
                                     output_type=pytesseract.Output.DICT)
    blocks = []
    for i, text in enumerate(data["text"]):
        if not str(text).strip():
            continue
        conf = float(data["conf"][i]) / 100.0
        if conf <= 0:
            continue
        blocks.append({"text": str(text).strip(), "x": int(data["left"][i]), "y": int(data["top"][i]),
                       "w": int(data["width"][i]), "h": int(data["height"][i]), "conf": round(conf, 3)})
    return blocks, "pytesseract"


def _ocr_tesseract_cli(path: Path, lang: str):
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("tesseract не найден в PATH")
    out = subprocess.run([exe, str(path), "stdout", "-l", lang, "tsv"],
                         capture_output=True, text=True, check=True).stdout
    blocks = []
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or not parts[11].strip():
            continue
        conf = float(parts[10]) / 100.0
        if conf <= 0:
            continue
        blocks.append({"text": parts[11].strip(), "x": int(parts[6]), "y": int(parts[7]),
                       "w": int(parts[8]), "h": int(parts[9]), "conf": round(conf, 3)})
    return blocks, "tesseract_cli"


def ocr_image(path: Path, cfg: dict) -> tuple[list[dict], str]:
    engines = {"rapidocr": lambda: _ocr_rapidocr(path),
               "paddleocr": lambda: _ocr_paddleocr(path),
               "pytesseract": lambda: _ocr_pytesseract(path, cfg["ocr"]["lang"]),
               "tesseract_cli": lambda: _ocr_tesseract_cli(path, cfg["ocr"]["lang"])}
    errors = []
    for name in cfg["ocr"]["engines"]:
        try:
            blocks, engine = engines[name]()
            if blocks:
                return blocks, engine
            errors.append(f"{name}: пустой результат")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}: {e}")
    raise RuntimeError("OCR недоступен. Установите один из движков:\n"
                       "  pip install rapidocr-onnxruntime        (легкий, быстрый, CPU)\n"
                       "  pip install paddleocr paddlepaddle      (точнее на русском)\n"
                       "  pip install pytesseract  + Tesseract-OCR с языком rus\n"
                       "Подробности: docs/08_SCREEN_UNDERSTANDING.md\nПопытки:\n  " + "\n  ".join(errors))


# ─────────────────────── структура текста
def cluster_lines(blocks: list[dict], y_tol_ratio: float = 0.6) -> list[dict]:
    lines: list[dict] = []
    for b in sorted(blocks, key=lambda b: (b["y"], b["x"])):
        center = b["y"] + b["h"] / 2
        for ln in lines:
            if abs(center - (ln["y"] + ln["h"] / 2)) <= max(ln["h"], b["h"]) * y_tol_ratio:
                ln["blocks"].append(b)
                ln["y"], ln["h"] = min(ln["y"], b["y"]), max(ln["h"], b["h"])
                break
        else:
            lines.append({"y": b["y"], "h": b["h"], "blocks": [b]})
    for ln in lines:
        ln["blocks"].sort(key=lambda b: b["x"])
        ln["text"] = " | ".join(b["text"] for b in ln["blocks"])
    return sorted(lines, key=lambda ln: ln["y"])


def _number_with_unit(text: str, pat: dict, max_gap: int = 14):
    """Ищет «число + единица» в тексте блока. Единица может стоять до или после числа."""
    for m in pat["number"].finditer(text):
        raw = m.group(0).replace(",", ".")
        try:
            val = float(raw)
        except ValueError:
            continue
        after = text[m.end(): m.end() + max_gap]
        before = text[max(0, m.start() - max_gap): m.start()]
        for where in (after, before):
            for rx, unit, metric in pat["units"]:
                if rx.search(where):
                    return round(val, 3), unit, metric
    return None


def _canon_id(oid: str, known: set[str] | None) -> str:
    oid = oid.upper()
    if not known or oid in known:
        return oid
    variants = {oid.replace("-", ""), re.sub(r"^([A-Z]+)(\d)", r"\1-\2", oid),
                re.sub(r"^([A-Z]+)-?(\d)", r"\1-\2", oid)}
    for v in variants:
        if v in known:
            return v
    return oid


def _column_unit_hint(block: dict, blocks: list[dict], pat: dict):
    """Для таблиц: единица измерения берётся из заголовка столбца (блок выше с тем же x)."""
    for b in blocks:
        if b["y"] + b["h"] >= block["y"]:
            continue
        dx_overlap = min(b["x"] + b["w"], block["x"] + block["w"]) - max(b["x"], block["x"])
        if dx_overlap < 0.5 * block["w"] or (block["y"] - (b["y"] + b["h"])) > 260:
            continue
        for rx, unit, metric in pat["units"]:
            if rx.search(b["text"]):
                return unit, metric
    return None


def find_objects(blocks: list[dict], lines: list[dict], pat: dict, known: set[str] | None) -> dict:
    objs: dict[str, dict] = {}
    for b in blocks:
        for kind in ("node", "link"):
            for rx in pat[kind]:
                for m in rx.finditer(b["text"]):
                    oid = _canon_id(m.group(0), known)
                    rec = objs.setdefault(oid, {"id": oid, "type": "junction" if kind == "node" else "pipe",
                                                "hits": 0, "blocks": []})
                    rec["hits"] += 1
                    if b not in rec["blocks"]:
                        rec["blocks"].append(b)

    for oid, rec in objs.items():
        # 1) значение в том же блоке, 2) в блоке справа на той же строке, 3) единица из заголовка столбца
        for b in rec["blocks"]:
            got = _number_with_unit(b["text"], pat)
            if got:
                rec["value"], rec["unit"], rec["metric"] = got
                rec["source"] = "same_block"
                break
        if "value" not in rec:
            # идём по блокам слева направо по строке: «число + единица» или «число + единица из заголовка»
            for b in rec["blocks"]:
                for neighbor in _right_candidates(b, blocks):
                    got = _number_with_unit(neighbor["text"], pat)
                    if got:
                        rec["value"], rec["unit"], rec["metric"] = got
                        rec["source"] = "right_neighbor"
                        break
                    m = pat["number"].search(neighbor["text"])
                    hint = _column_unit_hint(neighbor, blocks, pat) if m else None
                    if m and hint:
                        rec["value"] = round(float(m.group(0).replace(",", ".")), 3)
                        rec["unit"], rec["metric"] = hint
                        rec["source"] = "table_column"
                        break
                if "value" in rec:
                    break
    return objs


def attach_field_values(objs: dict, lines: list[dict], pat: dict, cfg: dict) -> None:
    """Панель свойств объекта: значения полей (Отметка / Спрос / Давление) — его собственные.

    Для узла «ценность» — давление (если поле есть), иначе расход, иначе отметка/уровень.
    """
    if len(objs) != 1:
        return
    _oid, rec = next(iter(objs.items()))
    label_metrics = [(re.compile(m["regex"], re.I), m["metric"]) for m in cfg["patterns"].get("label_metrics", [])]
    fields: dict[str, dict] = {}
    for ln in lines:
        blocks = ln["blocks"]
        for i, b in enumerate(blocks):
            metric_from_label = None
            for rx, metric in label_metrics:
                if rx.search(b["text"]):
                    metric_from_label = metric
                    break
            unit_hit = None
            for rx, unit, _metric in pat["units"]:
                if rx.search(b["text"]):
                    unit_hit = unit
                    break
            if not (metric_from_label and unit_hit):
                continue
            for nb in blocks[i + 1:]:
                m = pat["number"].search(nb["text"])
                if m:
                    fields[metric_from_label] = {"value": round(float(m.group(0).replace(",", ".")), 3),
                                                 "unit": unit_hit}
                    break
    if not fields:
        return
    rec["fields"] = fields
    if "value" not in rec:
        for metric in ("pressure", "flow", "elevation", "level", "velocity"):
            if metric in fields:
                rec["value"] = fields[metric]["value"]
                rec["unit"] = fields[metric]["unit"]
                rec["metric"] = metric
                rec["source"] = "editor_field"
                break


def _right_candidates(block: dict, blocks: list[dict], max_dx: int = 320) -> list[dict]:
    """Блоки той же строки правее данного, по возрастанию x (колонки таблицы)."""
    out = []
    for b in blocks:
        if b is block or b["x"] <= block["x"]:
            continue
        same_line = abs((b["y"] + b["h"] / 2) - (block["y"] + block["h"] / 2)) <= max(block["h"], b["h"]) * 0.7
        if same_line and (b["x"] - (block["x"] + block["w"])) < max_dx:
            out.append(b)
    return sorted(out, key=lambda b: b["x"])


# ─────────────────── тип экрана и панели
def classify(lines: list[dict], objs: dict, pat: dict, cfg: dict) -> tuple[str, dict, dict]:
    text = " \n ".join(ln["text"] for ln in lines).lower()
    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for stype, kws in cfg["keywords"].items():
        found = [k for k in kws if k.lower() in text]
        if found:
            hits[stype] = found
        scores[stype] = 2.0 * len(found)

    n_lines_2nums = sum(1 for ln in lines
                        if len(pat["number"].findall(ln["text"])) >= 2)
    n_values = sum(1 for o in objs.values() if "value" in o)
    if n_lines_2nums >= 3:
        scores["results_table"] = scores.get("results_table", 0) + 3.0
    if len(objs) >= 2 and n_values == 0:
        scores["map"] = scores.get("map", 0) + 2.0
    n_long = sum(1 for ln in lines if len(ln["text"]) > 60)
    if n_long >= 3:
        scores["report"] = scores.get("report", 0) + 3.0
    n_fields = sum(1 for k in ("отметка", "elevation", "спрос", "demand", "диаметр", "diameter",
                               "шероховатость", "roughness") if k in text)
    if n_fields >= 2 and len(objs) == 1:
        scores["object_editor"] = scores.get("object_editor", 0) + 3.0
    if ("график" in text or "time series" in text or "series" in text) and n_values == 0:
        scores["time_series"] = scores.get("time_series", 0) + 3.0

    panels = sorted([s for s, v in scores.items() if v >= 2.0], key=lambda s: -scores[s])
    if scores:
        best = max(scores, key=scores.get) if max(scores.values()) > 0 else "unknown"
    else:
        best = "unknown"
    confidence = 0.45 + 0.08 * min(scores.get(best, 0), 6) if best != "unknown" else 0.25
    return best, hits, {"confidence": round(min(confidence, 0.95), 3), "panels": panels,
                        "table_lines": n_lines_2nums, "long_lines": n_long, "field_hints": n_fields}


def parse_timestep(lines: list[dict], pat: dict) -> dict | None:
    for ln in lines:
        for rx in pat["timestep"]:
            m = rx.search(ln["text"])
            if m:
                try:
                    h = float(m.group(1))
                except (TypeError, ValueError):
                    continue
                if 0 <= h <= 24:
                    return {"hour": h, "source": "ocr_text"}
    return None


# ─────────────────── выбор объекта и неоднозначность
def pick_selected(objs: dict, cfg: dict, known: set[str] | None) -> tuple[dict | None, dict, list]:
    notes: list[str] = []
    if not objs:
        return None, {"level": "high", "notes": ["на экране не распознан ни один объект сети"]}, []

    n_values = sum(1 for o in objs.values() if "value" in o)
    max_ok = cfg["ambiguity"]["max_objects_with_values_for_selection"]
    scored = []
    for o in objs.values():
        s = (1.0 if "value" in o else 0.0) + min(o["hits"], 3) * 0.2
        if known and o["id"] in known:
            s += 0.3
        scored.append({"id": o["id"], "score": round(s, 3), "type": o["type"],
                       "has_value": "value" in o})
    scored.sort(key=lambda x: -x["score"])

    if known:
        unknown = [o["id"] for o in objs.values() if o["id"] not in known]
        if unknown:
            notes.append("нет в сети: " + ", ".join(sorted(unknown)))

    if n_values > max_ok:
        notes.append(f"на экране {n_values} объектов со значениями — выбранный по OCR не определить")
        return None, {"level": "high", "notes": notes, "candidates": scored[:5]}, scored
    if len(scored) > 1 and abs(scored[0]["score"] - scored[1]["score"]) < 0.15:
        notes.append("два объекта с близкой уверенностью")
        return None, {"level": "medium", "notes": notes, "candidates": scored[:5]}, scored

    best = scored[0]
    oid = best["id"]
    level = "low" if (best["has_value"] or best["score"] >= 1.2) else "medium"
    if level == "medium":
        notes.append("объект найден без привязанного значения")
    obj = {"id": oid, "type": objs[oid]["type"],
           "confidence": round(min(0.55 + 0.15 * best["score"], 0.97), 3),
           "source": objs[oid].get("source", "label")}
    return obj, {"level": level, "notes": notes, "candidates": scored[:5]}, scored


def suggest_actions(screen_type: str, sel: dict | None, timestep: dict | None, cfg: dict) -> list[dict]:
    acts = []
    for intent in cfg["suggested_actions"].get(screen_type, []):
        params: dict = {}
        if intent in ("select_object", "focus_entity", "explain_object", "zoom_to_object"):
            if not sel:
                continue
            params = {"object": sel["id"]}
        if intent == "set_timestep":
            if not timestep:
                continue
            params = {"hour": timestep["hour"]}
        if intent == "compare_with_baseline" and sel:
            params = {"object": sel["id"]}
        acts.append({"intent": intent, "params": params,
                     "requires_confirmation": intent in ("export_report", "set_timestep", "zoom_to_object")})
    return acts


def description_ru(det: dict) -> str:
    titles = {"map": "карту сети", "results_table": "таблицу результатов расчёта",
              "object_editor": "панель свойств объекта", "time_series": "график временного ряда",
              "report": "текстовый отчёт", "form": "форму ввода данных",
              "dialog": "диалоговое окно", "unknown": "экран, который не удалось однозначно распознать"}
    parts = [f"Пользователь смотрит на {titles.get(det['screen_type'], det['screen_type'])}."]
    so = det.get("selected_object")
    parts.append(f"Выбран объект {so['id']}." if so else "Выбранный объект не определён.")
    ts = det.get("timestep")
    if ts:
        parts.append(f"Расчётное время — {ts['hour']:g} ч.")
    vos = [v for v in det.get("visible_objects", []) if v.get("value") is not None]
    if vos:
        shown = ", ".join(f"{v['id']} — {v['value']:g} {v.get('unit') or ''}".strip() for v in vos[:5])
        parts.append(f"На экране видны значения: {shown}.")
    if det["ambiguity"]["level"] != "low":
        parts.append("Внимание: " + "; ".join(det["ambiguity"].get("notes") or ["данные экрана неоднозначны"]) + ".")
    return " ".join(parts)


# ─────────────────── сборка результата
def detect_from_blocks(blocks: list[dict], cfg: dict | None = None,
                       known: set[str] | None = None, screen_id: str = "",
                       engine: str = "ocr_blocks") -> dict:
    cfg = cfg or load_cfg()
    pat = compile_patterns(cfg)
    min_conf = cfg["ocr"]["min_block_confidence"]
    blocks = [b for b in blocks if b.get("conf", 1.0) >= min_conf]
    if not blocks:
        raise RuntimeError("после фильтра по confidence не осталось текстовых блоков")

    lines = cluster_lines(blocks)
    screen_type, hits, extra = classify(lines, {}, pat, cfg)
    objs = find_objects(blocks, lines, pat, known)
    screen_type, hits, extra = classify(lines, objs, pat, cfg)
    if screen_type == "object_editor":
        attach_field_values(objs, lines, pat, cfg)
    sel, ambiguity, candidates = pick_selected(objs, cfg, known)

    confidence = extra["confidence"]
    if ambiguity["level"] == "high":
        confidence = min(confidence, 0.55)
    elif ambiguity["level"] == "medium":
        confidence = min(confidence, 0.75)
    if known:
        confidence = min(confidence + 0.05, 0.98)

    visible = []
    for o in sorted(objs.values(), key=lambda o: (-(o.get("value") is not None), o["id"]))[:12]:
        visible.append({"id": o["id"], "type": o["type"], "value": o.get("value"),
                        "unit": o.get("unit"), "metric": o.get("metric"),
                        "source": o.get("source", "label")})

    timestep = parse_timestep(lines, pat)
    det = {
        "schema_version": "1.0",
        "screen_id": screen_id,
        "app": "epanet_ai" if any(k in " ".join(ln["text"] for ln in lines).lower()
                                 for k in ("vn01", "vn-01", "epanet-ai", "ассистент")) else "unknown",
        "screen_type": screen_type,
        "confidence": round(confidence, 3),
        "evidence": {"source": "ocr+heuristics", "engines": [engine], "ocr_blocks": len(blocks),
                     "matched_keywords": hits,
                     "network_check": ("no_inp" if known is None else
                                       ("ok" if not ambiguity.get("notes") else "check_notes"))},
        "network": {"id": None, "source": "none"},
        "timestep": timestep,
        "selected_object": sel,
        "visible_objects": visible,
        "panels": extra["panels"] or [screen_type],
        "actions": suggest_actions(screen_type, sel, timestep, cfg),
        "ambiguity": {"level": ambiguity["level"], "notes": ambiguity.get("notes", []),
                      "candidates": candidates[:5]},
    }
    det["ui_context"] = {
        "screen_type": screen_type,
        "selected_object": (sel or {}).get("id"),
        "object_type": (sel or {}).get("type"),
        "timestep_h": (timestep or {}).get("hour"),
        "confidence": det["confidence"],
        "description_ru": "",
    }
    det["ui_context"]["description_ru"] = description_ru(det)
    return det


# ─────────────────── CLI
def main() -> None:
    ap = argparse.ArgumentParser(description="Определение содержимого экрана (скриншот → JSON)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", help="файл скриншота (нужен установленный OCR)")
    src.add_argument("--ocr-blocks", help="готовые OCR-блоки в JSON (офлайн-режим)")
    ap.add_argument("--inp", default=None, help="сеть .inp для сверки ID (необязательно)")
    ap.add_argument("--screen-id", default="", help="идентификатор скриншота")
    ap.add_argument("--out", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = load_cfg()
    known = known_ids_from_inp(args.inp)
    if args.ocr_blocks:
        blocks = json.loads(Path(args.ocr_blocks).read_text(encoding="utf-8"))
        if isinstance(blocks, dict):
            blocks = blocks.get("blocks", [])
        engine = "ocr_blocks"
        screen_id = args.screen_id or Path(args.ocr_blocks).stem
    else:
        blocks, engine = ocr_image(Path(args.image), cfg)
        screen_id = args.screen_id or Path(args.image).stem

    det = detect_from_blocks(blocks, cfg, known, screen_id, engine)
    errs = schema.validate(det)
    if errs:
        print("Ошибки схемы:", *errs, sep="\n  ")
    if args.out:
        out = common.ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(det, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.quiet:
            print(f"→ {out}")
    if not args.quiet:
        print(json.dumps({k: det[k] for k in ("screen_type", "confidence", "selected_object",
                                              "timestep", "ambiguity")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
