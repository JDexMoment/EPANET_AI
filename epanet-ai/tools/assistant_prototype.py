"""Прототип ассистента: «что на экране» + модель сети → карточка объекта.

Идея программы (вариант A): пользователь бросает скриншот AquaBit и файл модели
(`.inp`, `.NET`, `.epanet`); ассистент объясняет, что на экране, **и** подтягивает
точные данные из модели: параметры объекта, соседей по сети, правила управления,
расчёт (скорость, удельные потери) — плюс графики и готовый контекст для VLM.

Этот скрипт — детерминированная половина такого приложения (без нейросети):
сюда VLM будет передавать «видимый текст» экрана (или ID объектов), а на выходе
получается карточка, которую модель только пересказывает своими словами.

Запуск:
    # по ответу/OCR со скриншота: сами найдём ID объектов и расходы
    python tools/assistant_prototype.py --model "модель для ИИ — копия.txt" \
        --screen semey/dataset/answers/slide_09.txt --out semey/work/assistant_demo

    # явно указать объект и расход
    python tools/assistant_prototype.py --model model.inp --objects 3459843 --q 87.9 --out out/

Результат: `card.html` (карточка с графиками), `context_for_vlm.txt` (факты для модели),
`facts.json` (машинный вид).
"""
from __future__ import annotations

import argparse
import base64
import decimal
import html
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import model_io           # noqa: E402
from src import common             # noqa: E402
from tools.extract_claims import clean_text as clean_screen_text   # noqa: E402

ID_RE = re.compile(r"\b(\d{6,9})\b")
Q_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*м³/ч")
HIDE_SUFFIXES = (".txt", ".png", ".jpg", ".jpeg")

STATUS_RU = {"open": "открыта", "closed": "закрыта", "cv": "с обратным клапаном"}
MIN_V_SILT, GOOD_V, MAX_V = 0.3, 0.7, 1.5     # м/с: заиливание / норма / высокие потери


# ─────────────────────────────────────────────────────────── индекс модели

def build_index(model: model_io.ModelData) -> dict:
    """Индекс объектов: параметры, соседи, правила, упоминания в [PRESS]."""
    idx: dict[str, dict] = {"pipes": {}, "nodes": {}, "pumps": {}, "edges": {}, "rules": {}, "press": {}}

    def add_edge(eid: str, n1: str, n2: str):
        idx["edges"][eid] = (n1, n2)

    for row in model.rows("PIPES"):
        p = row.split(";")[0].split()
        if len(p) >= 6:
            status = p[6] if len(p) > 6 and not _isnum(p[6]) else "Open"
            idx["pipes"][p[0]] = {"n1": p[1], "n2": p[2], "length": float(p[3]),
                                  "d": float(p[4]), "c": float(p[5]), "status": status}
            add_edge(p[0], p[1], p[2])
    for row in model.rows("PUMPS"):
        p = row.split(";")[0].split()
        if len(p) >= 3:
            curve = p[3] if len(p) > 3 else None
            idx["pumps"][p[0]] = {"n1": p[1], "n2": p[2], "curve": curve}
            add_edge(p[0], p[1], p[2])
    for row in model.rows("JUNCTIONS"):
        p = row.split(";")[0].split()
        if len(p) >= 2:
            idx["nodes"][p[0]] = {"type": "узел", "elev": float(p[1]),
                                  "demand": float(p[2]) if len(p) > 2 and _isnum(p[2]) else 0.0}
    for row in model.rows("RESERVOIRS"):
        p = row.split(";")[0].split()
        if len(p) >= 2:
            idx["nodes"][p[0]] = {"type": "источник", "head": float(p[1])}
    for row in model.rows("TANKS"):
        p = row.split(";")[0].split()
        if len(p) >= 6:
            idx["nodes"][p[0]] = {"type": "резервуар", "elev": float(p[1]), "init": float(p[2]),
                                  "min": float(p[3]), "max": float(p[4]), "d": float(p[5])}

    # спросы (может быть несколько строк на узел) и эмиттеры
    for row in model.rows("DEMANDS"):
        p = row.split(";")[0].split()
        if len(p) >= 2 and _isnum(p[1]):
            node = idx["nodes"].get(p[0])
            if node is not None:
                node["demand_total"] = node.get("demand_total", 0.0) + float(p[1])
    for row in model.rows("EMITTERS"):
        p = row.split(";")[0].split()
        if len(p) >= 2 and p[0] in idx["nodes"]:
            idx["nodes"][p[0]]["emitter"] = float(p[1])

    # правила: RULE … IF … THEN LINK <id> STATUS IS …
    rule_lines = model.rows("RULES")
    cur_id, cur_body = None, []
    for line in rule_lines + ["RULE __END__"]:
        if line.upper().startswith("RULE"):
            if cur_id:
                idx["rules"][cur_id] = cur_body
            cur_id, cur_body = line.split()[1] if len(line.split()) > 1 else None, []
        else:
            cur_body.append(line)

    # [PRESS] — кастомная секция AquaBit: отмечаем упомянутые объекты
    for row in model.rows("PRESS"):
        for tok in row.split():
            if tok.isdigit():
                idx["press"].setdefault(tok, []).append(row)
    return idx


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def rules_touching(idx: dict, obj_id: str) -> list[str]:
    out = []
    for rid, body in idx["rules"].items():
        if any(obj_id in line.split() for line in body):
            out.append(" • ".join(x.strip() for x in body))
    return out


def neighbours(idx: dict, node_id: str) -> list[tuple[str, str]]:
    """Соседи узла: (ID участка, краткое описание)."""
    out = []
    for eid, (a, b) in idx["edges"].items():
        if node_id in (a, b):
            other = b if a == node_id else a
            if eid in idx["pipes"]:
                p = idx["pipes"][eid]
                out.append((eid, f"труба Ø{p['d']:g} мм, {p['length']:g} м → узел {other}"))
            elif eid in idx["pumps"]:
                out.append((eid, f"насос → узел {other}"))
    return out


# ─────────────────────────────────────────────────────────── расчёт

def hydraulics(q: float, length: float, d_mm: float, c: float) -> dict:
    qq = q / 3600.0
    dd = d_mm / 1000.0
    area = 3.141592653589793 * dd * dd / 4.0
    v = abs(qq) / area if area else 0.0
    h = 10.67 * length * abs(qq) ** 1.852 / (c ** 1.852 * dd ** 4.87)
    return {"v": v, "i": h / length * 1000.0 if length else 0.0, "h": h,
            "regime": ("заиливание/застой" if v < MIN_V_SILT else
                       "нормальный" if v <= MAX_V else "высокие потери")}


# ─────────────────────────────────────────────────────────── карточка

def svg_or_png_chart(points: list[dict], d: float, c: float, known_q: list[float]) -> str | None:
    """График V(Q) для трубы. matplotlib — если есть; иначе None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return None
    qs = [x["q"] for x in points]
    vs = [x["v"] for x in points]
    fig, ax = plt.subplots(figsize=(6.4, 3.4), dpi=130)
    ax.plot(qs, vs, color="#1f6feb", lw=2, label="Скорость V(Q)")
    ax.axhspan(0, MIN_V_SILT, color="#f8d7da", alpha=.55, label="зона заиливания (<0.3 м/с)")
    ax.axhspan(MAX_V, max(vs) * 1.05, color="#fff3cd", alpha=.55, label="высокие потери (>1.5 м/с)")
    for k, q in enumerate(known_q):
        if qs and min(qs) <= q <= max(qs):
            v = next(x["v"] for x in points if x["q"] >= q)
            ax.plot([q], [v], "o", color="#d13438", ms=7)
            dy = 10 + 12 * k          # разводим подписи, чтобы не накладывались
            ax.annotate(f"{q:g} м³/ч → {v:.2f} м/с", (q, v), textcoords="offset points",
                        xytext=(10, dy), fontsize=8, color="#d13438")
    ax.set_xlabel("Расход Q, м³/ч")
    ax.set_ylabel("Скорость V, м/с")
    ax.set_title(f"Труба Ø{d:g} мм, C={c:g} — скорость потока")
    ax.grid(alpha=.25)
    ax.legend(fontsize=7)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def fact_card(idx: dict, obj_id: str, q_values: list[float]) -> dict | None:
    """Все факты по объекту + расчёт."""
    if obj_id in idx["pipes"]:
        p = idx["pipes"][obj_id]
        card = {"id": obj_id, "kind": "труба", **p}
        card["status_ru"] = STATUS_RU.get(p["status"].lower(), p["status"])
        card["calc"] = [{"q": q, **hydraulics(q, p["length"], p["d"], p["c"])} for q in q_values]
        card["neighbours"] = neighbours(idx, p["n1"]) + neighbours(idx, p["n2"])
        card["rules"] = rules_touching(idx, obj_id)
        card["press"] = idx["press"].get(obj_id, [])
        card["chart_points"] = [{"q": p["d"] * (k / 20), **hydraulics(p["d"] * (k / 20), p["length"], p["d"], p["c"])}
                                for k in range(1, 121)]
        return card
    if obj_id in idx["nodes"]:
        n = idx["nodes"][obj_id]
        card = {"id": obj_id, "kind": n["type"], **n}
        card["neighbours"] = neighbours(idx, obj_id)
        card["rules"] = rules_touching(idx, obj_id)
        card["press"] = idx["press"].get(obj_id, [])
        return card
    if obj_id in idx["pumps"]:
        pm = idx["pumps"][obj_id]
        card = {"id": obj_id, "kind": "насос", **pm,
                "neighbours": neighbours(idx, pm["n1"]) + neighbours(idx, pm["n2"]),
                "rules": rules_touching(idx, obj_id), "press": idx["press"].get(obj_id, [])}
        return card
    return None


def render_html(cards: list[dict], model: model_io.ModelData, screen_used: str, question: str) -> str:
    rows_html = []
    for c in cards:
        img = ""
        if c["kind"] == "труба":
            img = svg_or_png_chart(c["chart_points"], c["d"], c["c"],
                                   [x["q"] for x in c["calc"]]) or ""
        params = []
        if c["kind"] == "труба":
            params = [("Участок", f'{c["n1"]} → {c["n2"]}'), ("Длина", f'{c["length"]:g} м'),
                      ("Диаметр", f'{c["d"]:g} мм'), ("Шероховатость C", f'{c["c"]:g}'),
                      ("Статус", c["status_ru"])]
        elif c["kind"] in ("узел", "источник", "резервуар"):
            params = [("Тип", c["kind"])]
            if "elev" in c: params.append(("Отметка", f'{c["elev"]:g} м'))
            if "head" in c: params.append(("Напор", f'{c["head"]:g} м'))
            if c.get("demand_total") is not None: params.append(("Спрос (сумма)", f'{c.get("demand_total", 0):g} м³/ч'))
            if "emitter" in c: params.append(("Эмиттер", f'{c["emitter"]:g}'))
            if "init" in c: params.append(("Уровень", f'{c["init"]:g} / {c["min"]:g}–{c["max"]:g} м'))
        elif c["kind"] == "насос":
            params = [("Участок", f'{c["n1"]} → {c["n2"]}'), ("Кривая", str(c.get("curve")))]

        calc_html = ""
        if c.get("calc"):
            lines = []
            for x in c["calc"]:
                lines.append(f'<li><b>Q = {x["q"]:g} м³/ч</b> → V = {x["v"]:.3f} м/с · '
                             f'удельные потери i = {x["i"]:.3f} м/км · на участке {x["h"]:.4f} м '
                             f'<span class="tag">{x["regime"]}</span></li>')
            calc_html = f'<div class="block"><h3>Расчёт по модели</h3><ul>{"".join(lines)}</ul></div>'
        rules_html = (f'<div class="block"><h3>Правила управления</h3><ul>'
                      + "".join(f"<li>{html.escape(r)}</li>" for r in c["rules"]) + "</ul></div>") if c["rules"] else ""
        press_html = (f'<div class="block warn"><h3>Кастомная секция [PRESS] (AquaBit)</h3><ul>'
                      + "".join(f"<li><code>{html.escape(r)}</code></li>" for r in c["press"]) + "</ul></div>") if c.get("press") else ""
        neigh_html = (f'<div class="block"><h3>Соседние участки ({len(c["neighbours"])})</h3><ul>'
                      + "".join(f"<li>{html.escape(t)}</li>" for _, t in c["neighbours"][:12]) + "</ul></div>") if c.get("neighbours") else ""
        rows_html.append(f"""
        <section class="card">
          <h2>{c['kind'].capitalize()} <code>{html.escape(c['id'])}</code></h2>
          <table class="params">{''.join(f'<tr><th>{k}</th><td>{html.escape(str(v))}</td></tr>' for k, v in params)}</table>
          {calc_html}{img and f'<div class="block"><h3>График</h3><img src="{img}" alt="V(Q)"></div>'}{rules_html}{press_html}{neigh_html}
        </section>""")

    return f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Карточка объекта — ассистент AquaBit</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;background:#f6f8fa;color:#1c1e21}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#57606a;font-size:13px;margin-bottom:18px}}
 .card{{background:#fff;border:1px solid #d8dee4;border-radius:10px;padding:16px 18px;margin:0 0 16px;max-width:860px}}
 .card h2{{font-size:17px;margin:0 0 10px}} code{{background:#eef2f6;padding:1px 5px;border-radius:4px}}
 table.params{{border-collapse:collapse;font-size:14px;margin-bottom:10px}}
 table.params th{{text-align:left;color:#57606a;font-weight:500;padding:2px 16px 2px 0}}
 table.params td{{padding:2px 0}} ul{{margin:6px 0 0 18px}} li{{margin:3px 0;font-size:14px}}
 .block{{margin-top:12px}} .block h3{{font-size:14px;margin:0 0 4px;color:#24292f}}
 .tag{{background:#e8f0fe;color:#1f6feb;border-radius:10px;padding:1px 8px;font-size:12px;margin-left:6px}}
 .warn{{background:#fff8e6;border-left:3px solid #d4a72c;padding:8px 12px;border-radius:6px}}
 img{{max-width:100%;border:1px solid #e4e8ec;border-radius:8px}}
 .foot{{color:#57606a;font-size:12px;max-width:860px}}
</style>
<body>
<h1>Ассистент AquaBit — карточка объекта</h1>
<div class="sub">Модель: <code>{html.escape(Path(model.source).name)}</code> · формат: {model.fmt} ·
объектов в модели: труб {model.count('PIPES'):,}, узлов {model.count('JUNCTIONS'):,} ·
вопрос: «{html.escape(question)}»</div>
{''.join(rows_html) if rows_html else '<section class="card">Объекты не найдены — укажите --objects.</section>'}
<p class="foot">Числа в карточке посчитаны по модели (Хазен–Вильямс), а не взяты из ответа.
Эту карточку ассистент передаёт языковой модели как «факты»: модель рассказывает их словами
и не имеет права выдумывать другие числа. Расходы (Q) подставляются из видимого текста экрана
или задаются пользователем — сама модель их не знает.</p>
</body></html>"""


def build_context(cards: list[dict], question: str) -> str:
    """Текст-факты, который ассистент отдаёт модели вместе со скриншотом."""
    lines = [f"ВОПРОС: {question}", "", "ФАКТЫ ИЗ МОДЕЛИ (использовать только их, не выдумывать новые числа):"]
    for c in cards:
        lines.append(f"\n[{c['kind']} {c['id']}]")
        if c["kind"] == "труба":
            lines.append(f"  {c['n1']} → {c['n2']}; длина {c['length']:g} м; Ø{c['d']:g} мм; C={c['c']:g}; статус: {c['status_ru']}")
        for x in c.get("calc", []):
            lines.append(f"  при Q={x['q']:g} м³/ч: V={x['v']:.3f} м/с; i={x['i']:.3f} м/км; потери на участке {x['h']:.4f} м ({x['regime']})")
        for r in c.get("rules", [])[:4]:
            lines.append(f"  правило: {r}")
        for r in c.get("press", [])[:2]:
            lines.append(f"  [PRESS]: {r}")
    lines += ["", "ЗАДАЧА МОДЕЛИ: объяснить инженеру, что происходит на скриншоте, опираясь на эти факты;",
              "если фактов не хватает — сказать, каких данных нет."]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────── main

def main() -> int:
    ap = argparse.ArgumentParser(description="Прототип ассистента: модель + экран → карточка объекта")
    ap.add_argument("--model", required=True, help=".inp / .NET / .epanet — файл модели")
    ap.add_argument("--screen", default=None, help="текст со скриншота (OCR/VLM) — найдём ID и расходы")
    ap.add_argument("--objects", default=None, help="ID объектов через запятую (вместо --screen)")
    ap.add_argument("--q", type=float, default=None, help="расход м³/ч (если нет в --screen)")
    ap.add_argument("--question", default="Что здесь происходит?")
    ap.add_argument("--out", default="outputs/assistant")
    args = ap.parse_args()

    model = model_io.read_model(args.model)
    idx = build_index(model)
    print(f"модель: {Path(args.model).name} · формат {model.fmt} · труб {len(idx['pipes']):,} · "
          f"узлов {len(idx['nodes']):,} · насосов {len(idx['pumps']):,} · правил {len(idx['rules']):,}")

    screen_text = ""
    if args.screen:
        screen_text = clean_screen_text(Path(args.screen).read_text(encoding="utf-8", errors="replace"))

    ids: list[str] = []
    if args.objects:
        ids = [x.strip() for x in args.objects.split(",") if x.strip()]
    elif screen_text:
        for tok in ID_RE.findall(screen_text):
            if tok in idx["pipes"] or tok in idx["nodes"] or tok in idx["pumps"]:
                if tok not in ids:
                    ids.append(tok)

    q_values: list[float] = []
    if args.q is not None:
        q_values = [args.q]
    elif screen_text:
        seen = set()
        for m in Q_RE.finditer(screen_text):
            v = float(m.group(1).replace(",", "."))
            if v > 0 and v not in seen:
                seen.add(v)
                q_values.append(v)
        q_values = q_values[:3]

    print(f"найдено объектов: {len(ids)} {ids[:5]} · расходы из текста: {q_values}")

    cards = [c for c in (fact_card(idx, i, q_values) for i in ids) if c]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.html").write_text(render_html(cards, model, screen_text[:400], args.question), encoding="utf-8")
    (out / "context_for_vlm.txt").write_text(build_context(cards, args.question), encoding="utf-8")
    (out / "facts.json").write_text(json.dumps({"model": Path(args.model).name, "fmt": model.fmt,
                                                "objects": ids, "q": q_values, "cards": cards},
                                               ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for c in cards:
        print(f"  · {c['kind']} {c['id']}" + (f" — расчёт: " + ", ".join(
            f"Q={x['q']:g}→V={x['v']:.2f} м/с ({x['regime']})" for x in c.get("calc", [])) if c.get("calc") else ""))
    print(f"\nкарточка: {common.rel_to_root(out / 'card.html')}")
    print(f"контекст для модели: {common.rel_to_root(out / 'context_for_vlm.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
