"""Генерирует Excel-форму разметки (альтернатива HTML-форме).

Листы:
  «Инструкция»  — краткая памятка;
  «Разметка»    — по строке на кейс: контекст (KPI/алерты/подсказка) и поля для заполнения;
  «Справочники» — категории, severity, уверенность, проверки (для выпадающих списков).

Запуск:
    python tools/make_excel_form.py --batch data/batches/batch_exp_01_01.json
    python tools/make_excel_form.py --expert exp_01     # все партии эксперта в один файл
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from src import common  # noqa: E402

HEAD_FILL = PatternFill("solid", fgColor="1F3B57")
HEAD_FONT = Font(color="FFFFFF", bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")

COLUMNS = [
    ("case_id", 34, "ID кейса"),
    ("mode", 16, "Режим"),
    ("question", 46, "Вопрос пользователя"),
    ("alerts", 46, "Top-алерты (объект, значение, ссылка)"),
    ("kpi", 30, "KPI расчёта"),
    ("has_problem", 12, "Есть проблема? (да/нет)"),
    ("category", 22, "Категория"),
    ("severity", 12, "Severity"),
    ("confidence", 12, "Уверенность"),
    ("objects", 18, "Главные объекты"),
    ("evidence_refs", 18, "Ссылки E-xxx"),
    ("observations", 50, "Наблюдения (по одному в строке)"),
    ("causes", 50, "Причины: гипотеза | уверенность | чем проверить"),
    ("checks", 40, "Что проверить"),
    ("recommendations", 40, "Рекомендации"),
    ("limitations", 40, "Ограничения"),
    ("answer", 60, "Итоговый золотой ответ (80–320 слов, каждое число с (E-xxx))"),
    ("time_min", 10, "Время, мин"),
    ("comment", 30, "Комментарий ревьюеру"),
]


def build(batch_files: list[Path], out: Path) -> None:
    labels = common.load_yaml("configs/labels.yaml")
    wb = Workbook()

    # ── Инструкция
    ws = wb.active
    ws.title = "Инструкция"
    ws["A1"] = "Разметка инженерных кейсов EPANET-AI (Excel-форма)"
    ws["A1"].font = Font(bold=True, size=14)
    text = [
        "1. Лист «Разметка»: одна строка = один кейс. Серые столбцы заполнять НЕ нужно (это данные).",
        "2. Каждое число в ответах — со ссылкой на факт, например: давление 9,96 м (E-002).",
        "3. Разделяйте: НАБЛЮДЕНИЕ → ВЕРОЯТНАЯ ПРИЧИНА (с уверенностью и способом проверки) → РЕКОМЕНДАЦИЯ.",
        "4. Если данных не хватает — так и пишите: «данных недостаточно, нужно …».",
        "5. Не ссылайтесь на внешние нормативы и натурные данные, которых нет в форме.",
        "6. Полное ТЗ: docs/06_ENGINEER_TASKS.md.  Примеры: docs/examples/.",
        "7. Готовый файл положить в data/cases/inbox/ (или отправить разработчику).",
        "Приоритетнее HTML-форма (tools/ExpertCasePack_*.html): в ней есть контекст и проверки.",
    ]
    for i, line in enumerate(text, start=3):
        ws.cell(row=i, column=1, value=line)

    # ── Справочники
    wsd = wb.create_sheet("Справочники")
    for col, (name, items) in enumerate([
        ("categories", [c["id"] for c in labels["categories"]]),
        ("severity", [s["id"] for s in labels["severity"]]),
        ("confidence", [c["id"] for c in labels["confidence"]]),
        ("verification_actions", [a["id"] for a in labels["verification_actions"]]),
    ], start=1):
        wsd.cell(row=1, column=col, value=name).font = Font(bold=True)
        for r, v in enumerate(items, start=2):
            wsd.cell(row=r, column=col, value=v)

    # ── Разметка
    wsx = wb.create_sheet("Разметка")
    for c, (key, width, title) in enumerate(COLUMNS, start=1):
        cell = wsx.cell(row=1, column=c, value=title)
        cell.fill, cell.font, cell.alignment = HEAD_FILL, HEAD_FONT, WRAP
        wsx.column_dimensions[get_column_letter(c)].width = width
    wsx.freeze_panes = "C2"

    row = 2
    for bf in batch_files:
        batch = common.read_json(bf)
        for cid in batch["case_ids"]:
            fp = common.ROOT / "data" / "cases" / "pending" / f"{cid}.json"
            if not fp.exists():
                continue
            case = common.read_json(fp)
            sdir = common.ROOT / "data" / "scenarios" / case["scenario_id"]
            derived = common.read_json(sdir / "derived" / "derived_metrics.json")
            kpi = derived["kpi"]
            alerts = "; ".join(f"{a['object']}: {a['value']} {a['unit']} ({a['evidence_id']})"
                               for a in derived["top_problems"][:5])
            kpi_txt = (f"minP {kpi['min_pressure_m']} м ({kpi['min_pressure_node']}, {kpi['min_pressure_time_h']} ч); "
                       f"Vmax {kpi['max_velocity_mps']} м/с ({kpi['max_velocity_link']}); "
                       f"недоподача {kpi.get('unserved_volume_m3') or 0} м³")
            values = {
                "case_id": case["case_id"], "mode": case["mode"], "question": case["question"],
                "alerts": alerts, "kpi": kpi_txt,
            }
            for c, (key, _, _) in enumerate(COLUMNS, start=1):
                cell = wsx.cell(row=row, column=c, value=values.get(key))
                cell.alignment = WRAP
            row += 1

    # выпадающие списки
    last = row - 1
    if last >= 2:
        def dv(formula: str, col_letter: str, title: str):
            d = DataValidation(type="list", formula1=formula, allow_blank=True, showDropDown=False)
            d.promptTitle, d.prompt = title, "Выберите значение из списка"
            wsx.add_data_validation(d)
            d.add(f"{col_letter}2:{col_letter}{last}")
        dv("=Справочники!$A$2:$A$40", "G", "Категория")
        dv("=Справочники!$B$2:$B$10", "H", "Severity")
        dv("=Справочники!$C$2:$C$10", "I", "Уверенность")
        dv('"да,нет"', "F", "Есть проблема?")

    common.ensure_dir(out.parent)
    wb.save(out)
    print(f"Excel-форма → {out} ({last - 1 if last >= 2 else 0} кейсов)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Excel-форма для инженера")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--expert", default=None, help="собрать все партии эксперта")
    ap.add_argument("--out", default="data/engineer_forms/ExpertForm.xlsx")
    args = ap.parse_args()

    if args.batch:
        files = [common.ROOT / args.batch]
    else:
        files = sorted((common.ROOT / "data" / "batches").glob(
            f"batch_{args.expert}_*.json" if args.expert else "batch_*.json"))
    if not files:
        print("Партии не найдены — сначала make_batches.py")
        return
    out = common.ROOT / args.out if not args.expert else common.ROOT / f"data/engineer_forms/ExpertForm_{args.expert}.xlsx"
    build(files, out)


if __name__ == "__main__":
    main()
