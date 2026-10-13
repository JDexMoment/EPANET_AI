"""Рисует демонстрационные «скриншоты» для автотестов трека «скриншоты → ответ».

Данные синтетические: они нужны ТОЛЬКО чтобы проверить код импорта, разметки
групп, сборки датасета и метрик. В обучение они не попадают (tests/fixtures/).

Запуск:  python tools/make_demo_screens.py
Результат: tests/fixtures/screens_pairs/
    images/scr_XX.png      — «экраны» (таблица, график, схема сети)
    answers/scr_XX.txt     — «золотые» ответы (как будто от Gemini)
    ocr/scr_XX.txt         — текст, который «видно» на экране (для проверки groundig)
    gemini_export.jsonl    — тот же набор в формате выгрузки датасета (image+answer+question)
    README.md              — пометка о синтетике
"""
from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "screens_pairs"

W, H = 1280, 800
BG = (246, 247, 249)
PANEL = (255, 255, 255)
BORDER = (189, 195, 205)
TITLEBAR = (52, 73, 94)
TEXT = (32, 37, 43)
ACCENT = (176, 58, 46)
OK = (39, 126, 76)
GRID = (214, 219, 226)


def _window(title: str, subtitle: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 34], fill=TITLEBAR)
    d.text((12, 11), title, fill=(255, 255, 255))
    d.rectangle([16, 48, W - 16, H - 16], fill=PANEL, outline=BORDER)
    if subtitle:
        d.text((32, 62), subtitle, fill=TEXT)
    return img, d


def _table(d: ImageDraw.ImageDraw, x: int, y: int, headers: list[str],
           rows: list[list[str]], widths: list[int]) -> None:
    cx = x
    for h, w in zip(headers, widths):
        d.rectangle([cx, y, cx + w, y + 26], fill=(235, 238, 243), outline=BORDER)
        d.text((cx + 8, y + 7), h, fill=TEXT)
        cx += w
    for i, row in enumerate(rows):
        ry = y + 26 + i * 24
        cx = x
        for cell, w in zip(row, widths):
            d.rectangle([cx, ry, cx + w, ry + 24], fill=PANEL, outline=GRID)
            d.text((cx + 8, ry + 6), cell, fill=TEXT)
            cx += w


def _chart(d: ImageDraw.ImageDraw, box: list[int], series: list[tuple[list[float], tuple[int, int, int]]],
           y_min: float, y_max: float, label: str) -> None:
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=(252, 253, 255), outline=BORDER)
    for i in range(6):
        gy = y0 + (y1 - y0) * i / 5
        d.line([x0, gy, x1, gy], fill=GRID)
        val = y_max - (y_max - y_min) * i / 5
        d.text((x0 - 52, gy - 6), f"{val:.0f}", fill=TEXT)
    for hours in range(0, 25, 4):
        gx = x0 + (x1 - x0) * hours / 24
        d.line([gx, y0, gx, y1], fill=GRID)
        d.text((gx - 6, y1 + 6), str(hours), fill=TEXT)
    for values, color in series:
        pts = [(x0 + (x1 - x0) * h / 24, y1 - (y1 - y0) * (v - y_min) / (y_max - y_min))
               for h, v in enumerate(values)]
        d.line(pts, fill=color, width=3)
    d.text((x0 + 10, y0 + 8), label, fill=TEXT)


def _schema(d: ImageDraw.ImageDraw) -> None:
    nodes = {"J101": (250, 200), "J102": (450, 170), "J105": (654, 260), "J106": (860, 210)}
    links = [("P-101", "J101", "J102"), ("P-105", "J102", "J105"), ("P-106", "J105", "J106")]
    for name, a, b in links:
        ax, ay = nodes[a]
        bx, by = nodes[b]
        d.line([ax, ay, bx, by], fill=(70, 90, 120), width=4)
        d.text(((ax + bx) / 2 + 6, (ay + by) / 2 - 18), name, fill=TEXT)
    for name, (x, y) in nodes.items():
        color = ACCENT if name == "J105" else (58, 110, 165)
        d.ellipse([x - 16, y - 16, x + 16, y + 16], fill=color)
        d.text((x - 14, y + 20), name, fill=TEXT)
    d.text((980, 320), "R-1 (резервуар)", fill=TEXT)
    d.rectangle([960, 300, 1000, 340], outline=(58, 110, 165), width=3)


# ── 6 «экранов»: 3 таблицы с числами, 2 графика, 1 схема ────────────────────
def screen_table(hour: str, rows: list[list[str]], note: str) -> Image.Image:
    img, d = _window("EPANET 2.2 — net_01.inp", f"Таблица узлов · время {hour} · давление, м вод.ст.")
    _table(d, 32, 92, ["Узел", "Давление", "Отбор, л/с", "Напор"],
           rows, [140, 150, 150, 150])
    d.text((32, 92 + 26 + len(rows) * 24 + 18), note, fill=TEXT)
    d.text((32, 720), "Статус расчёта: завершён · шаг 1 ч · 24 шага", fill=TEXT)
    return img


def screen_chart(title: str, label: str, series, y_min: float, y_max: float, note: str) -> Image.Image:
    img, d = _window("EPANET 2.2 — net_01.inp", title)
    _chart(d, [110, 130, 1180, 560], series, y_min, y_max, label)
    d.text((110, 590), note, fill=TEXT)
    d.text((110, 720), "Профиль за 24 ч · шаг 1 ч", fill=TEXT)
    return img


def screen_map() -> Image.Image:
    img, d = _window("EPANET 2.2 — net_01.inp", "Схема сети · узлы и участки")
    _schema(d)
    d.text((32, 720), "Выбран узел J105 · давление 22.09 м · отбор 18.40 л/с", fill=TEXT)
    d.text((32, 692), "Аварийная подсветка: узлы с давлением ниже 25 м", fill=ACCENT)
    return img


def main() -> None:
    global OUT
    ap = argparse.ArgumentParser(description="Демо-скриншоты для автотестов (синтетика)")
    ap.add_argument("--out", default=str(OUT), help="куда сложить (по умолчанию tests/fixtures/screens_pairs)")
    args = ap.parse_args()
    OUT = Path(args.out)
    if not OUT.is_absolute():
        OUT = ROOT / OUT

    imgs = OUT / "images"
    ans = OUT / "answers"
    ocr = OUT / "ocr"
    for p in (imgs, ans, ocr):
        p.mkdir(parents=True, exist_ok=True)

    rows_low = [["J101", "56.15", "4.20", "64.30"], ["J102", "43.70", "6.10", "51.80"],
                ["J105", "22.09", "18.40", "30.20"], ["J106", "41.35", "5.60", "49.50"]]
    rows_norm = [["J101", "55.80", "4.10", "63.90"], ["J102", "44.20", "6.00", "52.30"],
                 ["J105", "38.60", "9.20", "46.70"], ["J106", "42.10", "5.40", "50.20"]]
    rows_night = [["J101", "58.40", "2.10", "66.50"], ["J102", "47.90", "3.40", "56.00"],
                  ["J105", "40.10", "4.80", "48.20"], ["J106", "44.60", "2.90", "52.70"]]

    pressure = [46, 45, 44, 43, 42, 41, 39, 36, 32, 28, 25, 23, 22, 24, 27, 31, 35, 39, 42, 44, 45, 46, 46, 46]
    flow = [-8, -9, -9, -7, -4, -1, 3, 7, 11, 14, 17, 19, 20, 19, 16, 13, 10, 7, 4, 1, -2, -5, -7, -8]

    screens = [
        (imgs / "scr_01.png", screen_table("12:00", rows_low,
         "Узел J105 — минимальное давление 22.09 м вод.ст. при отборе 18.40 л/с")),
        (imgs / "scr_02.png", screen_chart("Профиль давления в узле J105",
         "Давление, м вод.ст. (ось Y) · часы (ось X)", [(pressure, ACCENT)], 20, 50,
         "Минимум давления в узле J105 — 22 м на 12-13 часу суток")),
        (imgs / "scr_03.png", screen_map()),
        (imgs / "scr_04.png", screen_table("04:00", rows_night,
         "Ночной режим: отбор минимальный, давления в норме")),
        (imgs / "scr_05.png", screen_chart("Расход в участке P-105",
         "Расход, л/с (ось Y) · часы (ось X)", [(flow, (58, 110, 165))], -10, 22,
         "Направление потока меняется: минимум -9 л/с в 02-03 ч")),
        (imgs / "scr_06.png", screen_table("18:00", rows_norm,
         "Вечерний пик: давления в пределах нормы")),
    ]
    for path, img in screens:
        img.save(path)

    answers = {
        "scr_01": "На экране таблица узлов сети в 12:00. Давление в узле J105 упало до 22.09 м вод.ст. "
                  "при отборе 18.40 л/с, тогда как в соседних узлах давление 41.35-56.15 м. Это ниже "
                  "нормативного минимума 25 м, то есть в зоне J105 дефицит напора. Наиболее вероятно "
                  "падение давления связано с ростом отбора: 18.40 л/с выделяются на фоне 4-6 л/с "
                  "в остальных узлах. Стоит проверить положение задвижки на подводящем участке и "
                  "уставки насосной станции, а также убедиться, что отбор в узле не завышен в модели.",
        "scr_02": "На графике профиль давления в узле J105 за сутки. Давление падает с 46 до 22 м "
                  "вод.ст. к 12-13 часу, затем восстанавливается к 22 часам. Минимум 22 м совпадает "
                  "с максимальным отбором и означает нарушение нормального режима в дневные часы. "
                  "Характер кривой плавный, без разрывов и скачков, что говорит о постепенном росте "
                  "потребления, а не об аварии. Рекомендую сопоставить минимум давления с графиком "
                  "отбора крупных потребителей и проверить достаточность напора насосной станции.",
        "scr_03": "На экране схема сети из четырёх узлов J101, J102, J105, J106 и участков P-101, "
                  "P-105, P-106, подключённых к резервуару R-1. Узел J105 подсвечен аварийным цветом: "
                  "его давление 22.09 м ниже порога 25 м, отбор 18.40 л/с. Остальные узлы работают "
                  "в нормальном режиме. Проблема локальная — в зоне узла J105, участок P-105 "
                  "и P-106 связывают её с остальной сетью; стоит проверить пропускную способность "
                  "этих участков и положение арматуры.",
        "scr_04": "На экране таблица узлов в 04:00. Отбор минимальный (2.10-4.80 л/с), давления "
                  "40.10-58.40 м — в пределах нормы, узел J105 тоже в норме (40.10 м). Это значит, "
                  "что ночью сеть работает штатно и дефицита напора нет. Нарушение возникает "
                  "в дневные часы, а значит причина связана с расходом, а не с постоянным "
                  "сопротивлением участков или закрытой арматурой.",
        "scr_05": "На графике расход в участке P-105 за сутки. В ночные часы расход отрицательный "
                  "с минимумом -9 л/с около 02-03 часов, днём положительный с максимумом 20 л/с "
                  "около 12 часов. Смена направления потока говорит о том, что участок работает "
                  "как перемычка между зонами: ночью вода перетекает из соседней зоны. Это "
                  "объясняет ночное повышение давления и требует проверки настроек зонирования "
                  "и положения задвижек на границе зон.",
        "scr_06": "На экране таблица узлов в 18:00. Давления 38.60-55.80 м, минимальное в узле J105 "
                  "(38.60 м) при отборе 9.20 л/с — это в пределах нормы. Вечерний пик проходит без "
                  "нарушений режима. Данные согласуются с профилем давления: после 16 часов давление "
                  "восстанавливается, значит исходная система справляется с вечерним водопотреблением.",
    }
    for name, text in answers.items():
        (ans / f"{name}.txt").write_text(text + "\n", encoding="utf-8")

    visible = {
        "scr_01": "EPANET 2.2 net_01.inp Таблица узлов время 12:00 давление м вод.ст. "
                  "Узел Давление Отбор л/с Напор J101 56.15 4.20 64.30 J102 43.70 6.10 51.80 "
                  "J105 22.09 18.40 30.20 J106 41.35 5.60 49.50 Статус расчёта завершён шаг 1 ч 24 шага",
        "scr_02": "EPANET 2.2 net_01.inp Профиль давления в узле J105 Давление м вод.ст. часы "
                  "20 30 40 50 0 4 8 12 16 20 24 Минимум давления в узле J105 22 м на 12-13 часу суток",
        "scr_03": "EPANET 2.2 net_01.inp Схема сети узлы и участки J101 J102 J105 J106 P-101 P-105 "
                  "P-106 R-1 резервуар Выбран узел J105 давление 22.09 м отбор 18.40 л/с "
                  "Аварийная подсветка узлы с давлением ниже 25 м",
        "scr_04": "EPANET 2.2 net_01.inp Таблица узлов время 04:00 давление м вод.ст. "
                  "Узел Давление Отбор л/с Напор J101 58.40 2.10 66.50 J102 47.90 3.40 56.00 "
                  "J105 40.10 4.80 48.20 J106 44.60 2.90 52.70 Ночной режим отбор минимальный давления в норме",
        "scr_05": "EPANET 2.2 net_01.inp Расход в участке P-105 Расход л/с часы -10 0 10 20 "
                  "0 4 8 12 16 20 24 Направление потока меняется минимум -9 л/с в 02-03 ч",
        "scr_06": "EPANET 2.2 net_01.inp Таблица узлов время 18:00 давление м вод.ст. "
                  "Узел Давление Отбор л/с Напор J101 55.80 4.10 63.90 J102 44.20 6.00 52.30 "
                  "J105 38.60 9.20 46.70 J106 42.10 5.40 50.20 Вечерний пик давления в пределах нормы",
    }
    for name, text in visible.items():
        (ocr / f"{name}.txt").write_text(text + "\n", encoding="utf-8")

    # ── вторая раскладка датасета: выгрузка одним JSONL (image, question, answer, session)
    export = OUT / "gemini_export.jsonl"
    sessions = {"scr_01": "net_01/day_peak", "scr_02": "net_01/day_peak", "scr_03": "net_01/day_peak",
                "scr_04": "net_01/night", "scr_05": "net_01/night", "scr_06": "net_01/evening"}
    with export.open("w", encoding="utf-8") as f:
        for name in answers:
            f.write(json.dumps({
                "image": f"images/{name}.png",
                "question": "Что здесь происходит?",
                "answer": answers[name],
                "session": sessions[name],
            }, ensure_ascii=False) + "\n")

    (OUT / "README.md").write_text(textwrap.dedent("""\
        # screens_pairs — синтетические данные для автотестов

        Здесь лежат «скриншоты», «золотые ответы» и выгрузка датасета, **нарисованные
        скриптом** `tools/make_demo_screens.py`. Они нужны только для проверки кода
        (импорт → контроль качества → группы → сплиты → метрики) и НЕ попадают в обучение.

        Раскладка нарочно смешанная, чтобы проверить оба поддерживаемых вида датасета:
          • `gemini_export.jsonl` — выгрузка «одним файлом» (image / question / answer / session);
          • `answers/*.txt` — ответы отдельными файлами, где имя файла = имя картинки.

        Реальный датасет от заказчика кладётся в `data/screens/` (см. `data/README.md`).
    """), encoding="utf-8")

    def show(x: Path) -> str:
        try:
            return str(x.relative_to(ROOT))
        except ValueError:
            return str(x)

    print(f"Готово: {len(screens)} экранов в {show(imgs)}")
    print(f"Ответы: {show(ans)} · текст экрана: {show(ocr)}")
    print(f"Выгрузка одним файлом: {show(export)}")


if __name__ == "__main__":
    main()
