"""Извлечение «гидравлических утверждений» из ответов и проверка их по модели .inp.

Зачем. Ответы Gemini — это текст, но в нём спрятаны проверяемые числа: ID объектов,
диаметры, длины, расходы, скорости, потери. Этот инструмент вытаскивает их в таблицу
и **сверяет с моделью** (параметры из .inp + пересчёт скорости и потерь по Хазену–Вильямсу).

Результат — claims.csv: по строке на утверждение, с вердиктом:
  OK          — совпало с моделью (с учётом округления в ответе);
  Σ м/км      — совпало, но в ответе «м», а по расчёту это удельные потери (м/км);
  ✗           — расходится с моделью (кандидат на ошибку Gemini);
  нет данных  — объект в модели не найден или нечем проверить (например, расход
                зависит от расчёта в AquaBit, а не от параметров модели).

Это и есть ответ на вопрос «можно ли выделить из ответов полезную гидравлику»:
да, и сразу с автоматической верификацией. Такие строки — будущий «проверяльщик
выдуманных чисел» для готовой модели.

Запуск:
    python tools/extract_claims.py --answers путь/export.jsonl --inp "модель.inp" --out claims.csv
    python tools/extract_claims.py --answers путь/answers --inp model.inp      # папка с .txt
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aquabit_inp as ab  # noqa: E402

WINDOW = 420          # сколько символов вокруг ID считать «про этот объект»
TOL_D, TOL_L = 1.0, 0.05      # допуски: диаметр (мм), длина (м)
TOL_V = 0.015         # допуск по скорости (округление до 0.01 м/с)
TOL_I_REL = 0.12      # допуск по удельным потерям (12% — округление до 2 знаков)
ID_RE = re.compile(r"\b(\d{6,8})\b")


# ─────────────────────────────────────────────────────────── модель

def load_model(path: Path) -> dict:
    text, enc = ab.read_inp(path)
    sec = ab.parse_sections(text)
    model: dict[str, dict] = {}
    for row in sec.get("pipes", []):
        p = ab.split_row(row)[0]
        if len(p) >= 6:
            model[p[0]] = {"type": "труба", "n1": p[1], "n2": p[2],
                           "length": float(p[3]), "d": float(p[4]), "c": float(p[5]),
                           "status": ab.pipe_status(p) if len(p) >= 7 else "Open"}
    for row in sec.get("junctions", []):
        p = ab.split_row(row)[0]
        if len(p) >= 2:
            model[p[0]] = {"type": "узел", "elev": float(p[1]),
                           "demand": float(p[2]) if len(p) > 2 else 0.0}
    for row in sec.get("reservoirs", []):
        p = ab.split_row(row)[0]
        if len(p) >= 2:
            model[p[0]] = {"type": "источник", "head": float(p[1])}
    for row in sec.get("tanks", []):
        p = ab.split_row(row)[0]
        if len(p) >= 2:
            model[p[0]] = {"type": "резервуар", "elev": float(p[1])}
    for row in sec.get("pumps", []):
        p = ab.split_row(row)[0]
        if len(p) >= 3:
            model[p[0]] = {"type": "насос", "n1": p[1], "n2": p[2]}
    return model


# ─────────────────────────────────────────────────────── нормализация текста

def clean_text(t: str) -> str:
    """Убирает LaTeX-остатки, чтобы регулярки видели обычные числа и единицы."""
    t = re.sub(r"\$([^$]*)\$", r" \1 ", t)
    t = re.sub(r"\\text\s*\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\g[eq]e?\b", " ≥ ", t)
    t = re.sub(r"\\l[eq]e?\b", " ≤ ", t)
    t = t.replace(">=", " ≥ ").replace("<=", " ≤ ")
    t = re.sub(r"\\(?:mathrm|cdot|sim|approx|times|leq|geq|,|;|!| )", " ", t)
    t = re.sub(r"[{}]", " ", t)
    return re.sub(r"\s+", " ", t)


NUM = r"(\d+(?:[.,]\d+)?)"
PAT_D = re.compile(r"(?:диаметр\w*|Ø|\bD)\s*[=:№]?\s*" + NUM + r"\s*мм", re.I)
PAT_L = re.compile(r"(?:длина\w*|\bL)\s*[=:]?\s*" + NUM + r"\s*м\b", re.I)
PAT_Q = re.compile(NUM + r"\s*м³/ч")
PAT_V = re.compile(NUM + r"\s*м/с")
PAT_I = re.compile(NUM + r"\s*м/км")
PAT_LOSS = re.compile(r"(?:потери?\s+напора|потери?\s+давления)[^.]{0,40}?" + NUM + r"\s*м\b", re.I)
PAT_ELEV = re.compile(r"(?:отметк\w*|высот\w*|напор)\s*[=:]?\s*" + NUM + r"\s*м\b", re.I)

UNITS = {"d": "мм", "length": "м", "q": "м³/ч", "v": "м/с", "i": "м/км",
         "loss": "м", "elev": "м"}
# слова-маркеры того, что число — норматив/легенда/совет, а не параметр объекта
NORM_WORDS = ("рекоменд", "оптимальн", "норматив", "легенд", "порог", "диапазон",
              "экономич", "снип", "стандарт", "как правило", "следует", "должны",
              "целесообразн", "вариант", "предложен", "проектн", "зоне заилив")
PARAM_RU = {"d": "диаметр", "length": "длина", "q": "расход", "v": "скорость",
            "i": "удельные потери", "loss": "потери напора", "elev": "отметка/напор"}


def num(s: str) -> float:
    return float(s.replace(",", "."))


# ─────────────────────────────────────────────────────────── проверка

def verify(obj: dict, claim: dict) -> tuple[str, str]:
    """Возвращает (вердикт, что_по_модели)."""
    kind, value = claim["param"], claim["value"]
    t = obj["type"]
    if kind == "d":
        if t != "труба":
            return "нет данных", "диаметр — только у трубы"
        return (("OK" if abs(obj["d"] - value) <= TOL_D else "✗"), f'по модели Ø{obj["d"]:g} мм')
    if kind == "length":
        if t != "труба":
            return "нет данных", "длина — только у трубы"
        return (("OK" if abs(obj["length"] - value) <= TOL_L else "✗"),
                f'по модели L={obj["length"]:g} м')
    if kind == "elev":
        if t == "узел":
            return (("OK" if abs(obj["elev"] - value) <= 0.05 else "✗"),
                    f'по модели отметка {obj["elev"]:g} м')
        if t == "источник":
            return (("OK" if abs(obj["head"] - value) <= 0.05 else "✗"),
                    f'по модели напор {obj["head"]:g} м')
        return "нет данных", "нет отметки для этого типа"
    if kind in ("v", "i", "loss", "q") and t == "труба":
        if kind == "q":
            return "нет данных", "расход задаётся расчётом (брать выгрузку из AquaBit)"
        # скорости/потери проверяем по расходам, упомянутым в том же окне текста
        best, best_note = "нет данных", "в тексте нет расхода для пересчёта"
        qs = claim.get("ctx_q") or []
        if not qs and kind == "q":
            qs = [value]
        for q in qs:
            v, i, h = ab.headloss(q, obj["length"], obj["d"], obj["c"])
            if kind == "v" and abs(v - value) <= TOL_V:
                return "OK", f"расчёт при Q={q:g}: V={v:.3f} м/с, i={i:.3f} м/км"
            if kind == "i" and i and abs(i - value) <= max(0.01, TOL_I_REL * i):
                return "OK", f"расчёт при Q={q:g}: i={i:.3f} м/км"
            if kind == "loss":
                if abs(i - value) <= max(0.01, TOL_I_REL * i):
                    return "Σ м/км", f"при Q={q:g} это удельные потери i={i:.3f} м/км (полные на {obj['length']:g} м: {h:.4f} м)"
                if abs(h - value) <= max(0.002, 0.12 * h):
                    return "OK", f"расчёт при Q={q:g}: полные потери {h:.4f} м"
            best = "✗" if best == "нет данных" else best
            best_note = (f"расчёт при Q={q:g}: V={v:.3f} м/с, i={i:.3f} м/км, h={h:.4f} м")
        return best, best_note
    return "нет данных", "для этого типа объекта проверка не предусмотрена"


def claims_for_window(text: str, qs: list[float]) -> list[dict]:
    out = []
    for pat, kind in ((PAT_D, "d"), (PAT_L, "length"), (PAT_Q, "q"),
                      (PAT_V, "v"), (PAT_I, "i"), (PAT_LOSS, "loss"), (PAT_ELEV, "elev")):
        for m in pat.finditer(text):
            val = num(m.group(1))
            snippet = text[max(0, m.start() - 60): m.end() + 60].strip()
            if any(w in snippet.lower() for w in NORM_WORDS):
                continue          # это норматив/рекомендация, а не параметр объекта
            tail = text[max(0, m.start() - 5): m.start()]
            if re.search(r"[<>≤≥]", tail) or re.search(r"\d\s*[–—-]\s*$", tail):
                continue          # это порог или диапазон («≥ 10»), а не замер объекта
            out.append({"param": kind, "value": val, "snippet": snippet, "ctx_q": qs})
    # «с X до Y» — оба числа попадают в паттерны отдельными совпадениями, дубликаты неизбежны
    seen, uniq = set(), []
    for c in out:
        key = (c["param"], c["value"])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


# ─────────────────────────────────────────────────────────── вход/выход

def read_answers(path: Path) -> list[dict]:
    if path.is_dir():
        rows = []
        for f in sorted(path.rglob("*.txt")) + sorted(path.rglob("*.md")):
            rows.append({"id": f.stem, "answer": f.read_text(encoding="utf-8", errors="replace")})
        return rows
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Утверждения из ответов → проверка по .inp → CSV")
    ap.add_argument("--answers", required=True, help="папка с .txt или файл .jsonl (image/answer)")
    ap.add_argument("--inp", required=True, help="модель .inp (AquaBit-экспорт)")
    ap.add_argument("--out", default="claims.csv")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    model = load_model(Path(args.inp).expanduser())
    rows = read_answers(Path(args.answers).expanduser())
    print(f"модель: объектов {len(model):,} · ответов: {len(rows)}")

    out_rows: list[dict] = []
    n_ok = n_bad = n_na = 0
    for rec in rows:
        img = str(rec.get("image") or rec.get("image_file") or "")
        tag = rec.get("id") or (Path(img).stem if img else None) or rec.get("slide") or "?"
        text = clean_text(rec.get("answer") or "")
        if not text:
            continue
        # сначала все расходы в тексте — их используем для пересчёта скоростей/потерь
        qs_all = [num(m.group(1)) for m in PAT_Q.finditer(text)]
        for mid in ID_RE.finditer(text):
            obj_id = mid.group(1)
            obj = model.get(obj_id)
            if not obj:
                continue
            win = text[max(0, mid.start() - WINDOW): mid.end() + WINDOW]
            qs_win = [num(m.group(1)) for m in PAT_Q.finditer(win)] or qs_all[:4]
            for claim in claims_for_window(win, qs_win):
                verdict, note = verify(obj, claim)
                n_ok += verdict in ("OK", "Σ м/км")
                n_bad += verdict == "✗"
                n_na += verdict == "нет данных"
                out_rows.append({
                    "источник": tag, "объект": obj_id, "тип": obj["type"],
                    "параметр": PARAM_RU[claim["param"]],
                    "в_ответе": f'{claim["value"]:g} {UNITS[claim["param"]]}',
                    "по_модели": note, "вердикт": verdict,
                    "фрагмент": claim["snippet"][:160],
                })

    seen, uniq_rows = set(), []
    for r in out_rows:
        key = (r["источник"], r["объект"], r["параметр"], r["в_ответе"])
        if key not in seen:
            seen.add(key)
            uniq_rows.append(r)
    out_rows = uniq_rows
    n_ok = sum(1 for r in out_rows if r["вердикт"] in ("OK", "Σ м/км"))
    n_bad = sum(1 for r in out_rows if r["вердикт"] == "✗")
    n_na = sum(1 for r in out_rows if r["вердикт"] == "нет данных")

    out = Path(args.out)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["источник", "объект", "тип", "параметр", "в_ответе",
                                          "по_модели", "вердикт", "фрагмент"])
        w.writeheader()
        w.writerows(out_rows)

    print(f"утверждений: {len(out_rows)} · подтверждено: {n_ok} · расхождений: {n_bad} · нечем проверить: {n_na}")
    bad = [r for r in out_rows if r["вердикт"] == "✗"]
    if bad:
        print("\nрасхождения (кандидаты на ошибку Gemini):")
        for r in bad[:12]:
            print(f'  {r["источник"]} · {r["тип"]} {r["объект"]} · {r["параметр"]}: '
                  f'в ответе {r["в_ответе"]} — {r["по_модели"]}')
    print(f"\nтаблица: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
