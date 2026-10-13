"""Работа с .inp-экспортом AquaBit: сводка, поиск объектов, проверка чисел, конвертация.

Зачем этот инструмент. Заказчик прислал экспорт модели «Модель Семей» —
обычный EPANET-`.inp` (но в cp1251 и с расширениями AquaBit). Это **тот же проект**,
что на обуччающих скриншотах, поэтому по нему можно:

  * проверять «статические» числа из ответов Gemini — диаметр/длину/шероховатость
    трубы, отметку узла, спрос, паттерн (`link`, `node`);
  * проверять кинематику расхода: Q → V (м/с) и удельные потери i (м/км)
    по формуле Хазена–Вильямса (`link --q`);
  * готовить копию модели для ванильного EPANET/WNTR: статус из строки трубы
    переносится в `[STATUS]`, кастомные секции и опции AquaBit убираются (`convert`).

Команды:
    python tools/aquabit_inp.py stats   --inp "модель для ИИ — копия.txt"
    python tools/aquabit_inp.py link    --inp model.inp --id 3459843 --q 87.9
    python tools/aquabit_inp.py node    --inp model.inp --id 3382180
    python tools/aquabit_inp.py find    --inp model.inp --id 3459843
    python tools/aquabit_inp.py convert --inp model.inp --out model_epanet.inp

Важно про `convert`: он правит только формальные несовместимости. Кастомные опции
AquaBit (Overdemand, PumpMinInp, ALLOWPUMPREV, MinStepFreq, PrecPress, SmoothPattern)
и секция `[PRESS]` в ванильном EPANET не работают, поэтому полный суточный расчёт
в WNTR может быть непохож на расчёт AquaBit. Для верификации динамики (расходов во
времени) считайте в AquaBit — этот инструмент нужен для статики и арифметики.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

# нестандартные опции и секции AquaBit (в ванильном EPANET их нет)
AQUABIT_OPTIONS = (
    "SmoothPattern", "Overdemand", "MinStepFreq", "PrecPress", "ALLOWPUMPREV", "PumpMinInp",
)
AQUABIT_SECTIONS = ("press",)
COUNTED = ("junctions", "reservoirs", "tanks", "pipes", "pumps", "valves", "emitters",
           "demands", "patterns", "curves", "rules", "status", "controls", "coordinates")
STATUS_WORDS = ("open", "closed", "cv")


def read_inp(path: Path) -> tuple[str, str]:
    """Читает .inp, подбирая кодировку (AquaBit пишет cp1251)."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", errors="replace"), "cp1251/replace"


def split_row(line: str) -> tuple[list[str], str]:
    """Строка данных .inp → (токены, комментарий). AquaBit пишет хвостовые '; комментарии'."""
    data, _, comment = line.partition(";")
    return data.split(), comment.strip()


def parse_sections(text: str) -> dict[str, list[str]]:
    """Секции .inp → словарь {имя_секции_в_нижнем_регистре: [строки]}."""
    sections: dict[str, list[str]] = {}
    cur: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s.strip("[]").lower()
            sections.setdefault(cur, [])
            continue
        if cur is not None and s and not s.startswith(";"):
            sections[cur].append(s)
    return sections


# ---------------------------------------------------------------- объекты

def pipe_row(sections: dict[str, list[str]], obj_id: str) -> list[str] | None:
    for row in sections.get("pipes", []):
        parts = split_row(row)[0]
        if parts and parts[0] == obj_id:
            return parts
    return None


def pump_row(sections: dict[str, list[str]], obj_id: str) -> list[str] | None:
    for row in sections.get("pumps", []):
        parts = split_row(row)[0]
        if parts and parts[0] == obj_id:
            return parts
    return None


def pipe_status(parts: list[str]) -> str:
    """Статус трубы: он может стоять на месте minor loss (расширение AquaBit)."""
    word = parts[-1].lower()
    if word in STATUS_WORDS and not _is_number(word):
        return parts[-1]
    for tok in parts[6:]:
        if tok.lower() in STATUS_WORDS and not _is_number(tok):
            return tok
    return "Open"


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def headloss(q_m3h: float, length_m: float, d_mm: float, c: float) -> tuple[float, float]:
    """Возвращает (V м/с, i м/км) по Хазену–Вильямсу для Q в м³/ч и D в мм."""
    q = q_m3h / 3600.0
    d = d_mm / 1000.0
    area = math.pi * d * d / 4.0
    v = q / area if area else 0.0
    h = 10.67 * length_m * q ** 1.852 / (c ** 1.852 * d ** 4.87)
    return v, (h / length_m * 1000.0 if length_m else 0.0), h


# ---------------------------------------------------------------- команды

def cmd_stats(sections: dict[str, list[str]], args) -> int:
    counts = {s: len(rows) for s, rows in sections.items()}
    print("СЕКЦИИ (непустые):")
    for sec in COUNTED:
        if counts.get(sec):
            print(f"  [{sec:<12}] {counts[sec]:>7,}")
    extra = sorted(s for s in counts if s not in COUNTED and counts.get(s))
    if extra:
        print("  прочие:", ", ".join(f"[{s}] {counts[s]}" for s in extra))

    opts = {}
    for row in sections.get("options", []):
        parts = row.split(None, 1)
        if parts:
            opts[parts[0]] = parts[1] if len(parts) > 1 else ""
    for name in ("Units", "Headloss", "Demand Multiplier", "Trials", "Emitter Exponent"):
        if name in opts:
            print(f"  опция {name}: {opts[name]}")
    custom = [k for k in opts if any(k.lower() == c.lower() for c in AQUABIT_OPTIONS)]
    if custom:
        print("  кастом AquaBit:", ", ".join(f"{k}={opts[k]}" for k in custom))

    times = {r.split()[0].lower(): r.split()[-1] for r in sections.get("times", []) if r.split()}
    if times.get("duration"):
        print(f"  длительность: {times['duration']} (часы:мин) · гидрошаг {times.get('hydraulic', '—')}")
    pipes = [split_row(p)[0] for p in sections.get("pipes", [])]
    if pipes:
        dia = Counter(p[4] for p in pipes if len(p) > 4)
        rough = Counter(p[5] for p in pipes if len(p) > 5)
        d_top = ", ".join(f"{d} мм×{n}" for d, n in dia.most_common(4))
        r_top = ", ".join(f"{r}×{n}" for r, n in rough.most_common(3))
        print(f"  диаметры (топ): {d_top}")
        print(f"  шероховатость (топ-совпадения): {r_top}")
        closed = sum(1 for p in pipes if len(p) >= 7 and pipe_status(p).lower() == "closed")
        print(f"  труб с явным статусом Closed в строке: {closed}")
    if args.json:
        print(json.dumps({"counts": counts, "options": opts}, ensure_ascii=False, indent=1))
    return 0


def cmd_find(sections: dict[str, list[str]], args) -> int:
    hits = [(sec, row) for sec, rows in sections.items() for row in rows if args.id in split_row(row)[0]]
    print(f"ID {args.id}: найдено в {len(hits)} строках")
    for sec, row in hits[:20]:
        print(f"  [{sec}] {row}")
    if len(hits) > 20:
        print(f"  … ещё {len(hits) - 20}")
    return 0 if hits else 1


def cmd_link(sections: dict[str, list[str]], args) -> int:
    parts = pipe_row(sections, args.id)
    if parts:
        if len(parts) < 6:
            print(f"труба {args.id}: непонятная строка: {parts}")
            return 1
        n1, n2 = parts[1], parts[2]
        length = float(parts[3])
        dia = float(parts[4])
        rough = float(parts[5])
        status = pipe_status(parts)
        print(f"ТРУБА {parts[0]}: {n1} → {n2}")
        print(f"  длина {length:g} м · диаметр {dia:g} мм · шероховатость {rough:g} · статус {status}")
        if args.q is not None:
            v, i, h = headloss(args.q, length, dia, rough)
            print(f"  при Q = {args.q:g} м³/ч: V = {v:.3f} м/с · i = {i:.3f} м/км · h на участке = {h:.4f} м")
    parts = pump_row(sections, args.id)
    if parts:
        print(f"НАСОС {parts[0]}: {parts[1]} → {parts[2]} · {' '.join(parts[3:])}")
        for row in sections.get("status", []):
            if row.split()[0] == args.id:
                print(f"  статус в [STATUS]: {row}")
    if not pipe_row(sections, args.id) and not pump_row(sections, args.id):
        print(f"участок {args.id} не найден в [PIPES]/[PUMPS]")
        return 1
    return 0


def cmd_node(sections: dict[str, list[str]], args) -> int:
    for row in sections.get("junctions", []):
        parts = split_row(row)[0]
        if parts and parts[0] == args.id:
            print(f"УЗЕЛ {parts[0]}: отметка {parts[1]} м" + (f" · спрос {parts[2]}" if len(parts) > 2 else ""))
    for row in sections.get("reservoirs", []):
        parts = split_row(row)[0]
        if parts and parts[0] == args.id:
            print(f"ИСТОЧНИК (reservoir) {parts[0]}: напор {parts[1]} м")
    for row in sections.get("tanks", []):
        parts = split_row(row)[0]
        if parts and parts[0] == args.id:
            print(f"РЕЗЕРВУАР {parts[0]}: " + " ".join(parts[1:]))
    for row in sections.get("demands", []):
        parts = split_row(row)[0]
        if parts and parts[0] == args.id:
            print(f"  спрос: {' '.join(parts[1:])}")
    for row in sections.get("emitters", []):
        parts = split_row(row)[0]
        if parts and parts[0] == args.id:
            print(f"  эмиттер: {row}")
    for row in sections.get("press", []):
        if args.id in split_row(row)[0]:
            print(f"  строка [PRESS]: {row}")
    known = any(any(split_row(r)[0] and split_row(r)[0][0] == args.id for r in sections.get(sec, []))
                for sec in ("junctions", "reservoirs", "tanks"))
    if not known:
        print(f"узел {args.id} не найден")
        return 1
    return 0


def cmd_convert(sections_raw: dict[str, list[str]], text: str, args) -> int:
    """Пишет ванильный .inp: статус трубы → [STATUS], кастом AquaBit вырезается."""
    out_lines: list[str] = []
    moved: list[tuple[str, str]] = []
    skipped_sections = 0
    skip = False
    cur_sec = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur_sec = s.strip("[]").lower()
            skip = cur_sec in AQUABIT_SECTIONS
            if skip:
                skipped_sections += 1
                continue
            out_lines.append(line)
            continue
        if skip:
            continue
        if cur_sec == "options" and any(s.lower().startswith(k.lower()) for k in AQUABIT_OPTIONS):
            continue
        if cur_sec == "pipes":
            parts, comment = split_row(line)
            if len(parts) == 7 and parts[-1].lower() in STATUS_WORDS:
                # AquaBit пишет статус (Open/Closed/CV) там, где EPANET ждёт minor loss:
                # ставим minor loss = 0, статус остаётся на своём месте (8-е поле)
                moved.append((parts[0], parts[-1]))
                fixed = f" {parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[4]} {parts[5]} 0 {parts[6]}"
                if comment:
                    fixed += f" ;{comment}"
                out_lines.append(fixed)
                continue
        out_lines.append(line)

    if moved:
        kinds = Counter(st.lower() for _, st in moved)
        print(f"  выпрямлено строк труб со статусом: {len(moved)} "
              f"(closed={kinds.get('closed', 0)}, open={kinds.get('open', 0)}, cv={kinds.get('cv', 0)})")
        print("    (статус остаётся 8-м полем строки трубы — так это делает и ванильный EPANET)")

    out = Path(args.out).expanduser()
    out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"  вырезано кастомных секций: {skipped_sections} ({', '.join(AQUABIT_SECTIONS)})")
    print(f"  удалены кастомные опции: {', '.join(k for k in AQUABIT_OPTIONS)}")
    print(f"  записано: {out} (UTF-8)")
    print("  напоминание: ванильный EPANET не повторяет режим AquaBit — динамику сверяйте в AquaBit")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Утилиты для .inp-экспорта AquaBit (EPANET-форк)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("--inp", required=True, help="файл .inp (cp1251 или UTF-8)")
        return p

    p = add_common(sub.add_parser("stats", help="сводка по модели"))
    p.add_argument("--json", action="store_true")
    p = add_common(sub.add_parser("find", help="найти ID во всех секциях"))
    p.add_argument("--id", required=True)
    p = add_common(sub.add_parser("link", help="параметры участка (+ проверка Q→V→i)"))
    p.add_argument("--id", required=True)
    p.add_argument("--q", type=float, default=None, help="расход м³/ч для проверки скорости и потерь")
    p = add_common(sub.add_parser("node", help="параметры узла"))
    p.add_argument("--id", required=True)
    p = add_common(sub.add_parser("convert", help="собрать ванильный .inp для WNTR"))
    p.add_argument("--out", required=True)

    args = ap.parse_args(argv)
    path = Path(args.inp).expanduser()
    if not path.exists():
        print(f"нет файла {path}")
        return 2
    text, enc = read_inp(path)
    sections = parse_sections(text)
    print(f"# {path.name}: {enc}, строк {len(text.splitlines()):,}")
    if args.cmd == "stats":
        return cmd_stats(sections, args)
    if args.cmd == "find":
        return cmd_find(sections, args)
    if args.cmd == "link":
        return cmd_link(sections, args)
    if args.cmd == "node":
        return cmd_node(sections, args)
    if args.cmd == "convert":
        return cmd_convert(sections, text, args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
