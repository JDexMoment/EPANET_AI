"""Генератор автономных JSON, Markdown и HTML отчётов по проверке и очистке нулевых значений (ADR-0008)."""

from __future__ import annotations

import html
import json
from pathlib import Path

from aquabit_ai.zeros.cleaner import CorpusZeroAuditResult


def _fmt_bytes(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} МБ"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} КБ"
    return f"{num_bytes} Б"


def render_zero_audit_markdown(report: CorpusZeroAuditResult) -> str:
    """Формирует Markdown-отчёт проверки на нулевые значения и очистки 4 целевых таблиц."""
    mode_label = (
        "Аудит и удаление нулевых строк (4 целевые таблицы)"
        if report.mode == "clean_zeros"
        else "Диагностический аудит нулевых значений (без перезаписи файлов)"
    )
    lines: list[str] = [
        "# Отчёт проверки и очистки нулевых значений выгрузок AquaBit",
        "",
        f"- **Режим выполнения:** {mode_label}",
        f"- **Проверено моделей городов:** `{report.cities_count}`",
        f"- **Исходный объём CSV:** `{_fmt_bytes(report.size_bytes_before)}`",
        f"- **Объём после фильтрации нулевых строк:** `{_fmt_bytes(report.size_bytes_after)}` "
        f"(экономия `{_fmt_bytes(report.bytes_saved)}`, `-{report.bytes_saved_pct}%`)",
        f"- **Всего удалено нулевых строк:** `{report.total_rows_removed}`",
        "",
        "## Правила фильтрации 4 целевых таблиц и доменные инварианты (ADR-0008)",
        "",
        "1. **`Поток Насос.csv` (`p*`):** удаляются строки насосов, где **все** шаги расчёта `R0..R1439 == 0.0` (выключенные / резервные насосы). Циклические насосы с частичными нулями сохраняются.",
        "2. **`Потребители Узел.csv` (`c*`, `t*`):** удаляются записи абонентов, где `Потребление == 0` или пусто.",
        "3. **`Потребление Узел.csv` (`c*`):** удаляются строки узлов, где **все** шаги `R0..R1439 == 0.0` (промежуточные транзитные узлы).",
        "4. **`Узел.csv` (`c*`):** удаляются промежуточные узлы, где `Требуемое давление` не указано (пусто или `<= 0`). Список удалённых `c*` сохраняется в `pruned_zero_manifest.json` для ссылочной целостности `Напор Узел.csv` и `Труба.csv`.",
        "5. **Норматив требуемого давления (СП 31.13330.2021):** $H_{\\text{треб}} = 10 + 4(n - 1)$ м (10 м — 1 эт., 14 м — 2 эт., 18 м — 3 эт., 22 м — 4 эт., 26 м — 5 эт.).",
        "6. **Справочник Walski et al. (*Advanced Water Distribution Modeling and Management*, p. 40, Eq. 2.9):** скорость в круглой трубе определяется не как $Q/D$, а через площадь живого сечения $V = Q / A = 4Q / (\\pi D^2)$ (для $Q$ в $\\text{м}^3/\\text{ч}$ и $D$ в мм: $V\\ [\\text{м/с}] \\approx 353.67765 \\cdot |Q| / D^2$). По Принципу 1 расчёт скорости выполняется ядром AquaBit.",
        "",
    ]

    for city in report.cities:
        lines.extend(
            [
                f"## Город: `{city.city_name}` ({city.elapsed_ms:.1f} мс)",
                "",
                f"- **Объём CSV:** `{_fmt_bytes(city.size_bytes_before)}` -> `{_fmt_bytes(city.size_bytes_after)}` (`-{city.bytes_saved_pct}%`)",
                f"- **Удалено строк всего:** `{city.total_rows_removed}` "
                f"(транзитных узлов `Узел`: `{city.pruned_transit_nodes_count}`, "
                f"резервных насосов `Поток Насос`: `{city.pruned_standby_pumps_count}`, "
                f"нулевых абонентов `Потребители Узел`: `{city.pruned_zero_consumers_count}`, "
                f"нулевых строк `Потребление Узел`: `{city.pruned_zero_demand_matrix_rows_count}`)",
                f"- **Нарушений префиксов ID (`c/e/p/v/u/t`):** `{city.id_prefix_violations_count}`",
                f"- **Графиков потребления с числом строк != 24:** `{len(city.schedule_non_24h_ids)}`",
                "",
                "| Таблица | Целевая очистка | Строк (до -> после) | Удалено | Полностью 0-строк | Частично 0-строк | Пустых `null` | Правило / примечание |",
                "|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for t in city.tables:
            badge = "ДА" if t.is_clean_target else "нет"
            lines.append(
                f"| `{t.source_file}` | {badge} | `{t.rows_before} -> {t.rows_after}` | "
                f"`{t.rows_removed}` ({t.rows_removed_pct}%) | `{t.all_zero_rows_count}` ({t.all_zero_rows_pct}%) | "
                f"`{t.partial_zero_rows_count}` | `{t.null_cells_count}` | {t.cleaning_rule_applied} |"
            )
        lines.append("")

        if city.floor_distribution_by_required_pressure:
            lines.append("### Распределение конечных узлов-потребителей по этажности (`Требуемое давление`)")
            lines.append("")
            for label, cnt in sorted(city.floor_distribution_by_required_pressure.items()):
                lines.append(f"- **{label}:** `{cnt}` узлов")
            lines.append("")

    return "\n".join(lines)


def render_zero_audit_html(report: CorpusZeroAuditResult) -> str:
    """Формирует автономный HTML-отчёт (inline CSS, без внешних ресурсов) по проверке и очистке нулей."""
    mode_badge = (
        "ОЧИСТКА ВЫПОЛНЕНА (4 ЦЕЛЕВЫЕ ТАБЛИЦЫ)"
        if report.mode == "clean_zeros"
        else "РЕЖИМ АУДИТА (БЕЗ ИЗМЕНЕНИЯ ИСХОДНЫХ ФАЙЛОВ)"
    )

    city_sections: list[str] = []
    for city in report.cities:
        rows_html: list[str] = []
        for t in city.tables:
            row_bg = "background:#f0fdf4;" if t.is_clean_target else ""
            target_pill = (
                '<span style="display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;background:#dcfce7;color:#166534;">ОЧИСТКА</span>'
                if t.is_clean_target
                else '<span style="display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;background:#f1f5f9;color:#475569;">АУДИТ</span>'
            )
            details: list[str] = [html.escape(t.cleaning_rule_applied)]
            if t.removed_id_examples:
                sample = ", ".join(t.removed_id_examples[:8])
                suffix = f" … (всего {t.all_zero_rows_count})" if t.all_zero_rows_count > 8 else ""
                details.append(f"Нулевые ID: <code>{html.escape(sample)}{html.escape(suffix)}</code>")
            if t.kept_partial_zero_id_examples:
                kept_s = ", ".join(t.kept_partial_zero_id_examples[:6])
                details.append(
                    f"Сохранены с частичными нулями: <code>{html.escape(kept_s)}</code>"
                )
            for cs in t.column_stats:
                if cs.zero_count > 0 or cs.null_count > 0:
                    note_txt = f" — {html.escape(cs.note)}" if cs.note else ""
                    details.append(
                        f"Колонка <b>{html.escape(cs.column_name)}</b>: нулей=<code>{cs.zero_count}</code> ({cs.zero_pct}%), "
                        f"пустых null=<code>{cs.null_count}</code>{note_txt}"
                    )
            for w in t.warnings:
                details.append(f'<span style="color:#b45309;font-weight:600;">⚠ {html.escape(w)}</span>')

            rows_html.append(
                f"""<tr style="{row_bg}">
                    <td><strong>{html.escape(t.source_file)}</strong><br><small style="color:#64748b;">{html.escape(t.canonical_route)}</small></td>
                    <td>{target_pill}</td>
                    <td style="text-align:right;font-variant-numeric:tabular-nums;">{t.rows_before} &rarr; <strong>{t.rows_after}</strong></td>
                    <td style="text-align:right;font-variant-numeric:tabular-nums;color:#15803d;font-weight:700;">{t.rows_removed} ({t.rows_removed_pct}%)</td>
                    <td style="text-align:right;font-variant-numeric:tabular-nums;">{t.all_zero_rows_count} ({t.all_zero_rows_pct}%)</td>
                    <td style="text-align:right;font-variant-numeric:tabular-nums;">{t.partial_zero_rows_count}</td>
                    <td style="text-align:right;font-variant-numeric:tabular-nums;">{t.null_cells_count}</td>
                    <td style="text-align:right;font-variant-numeric:tabular-nums;">{_fmt_bytes(t.size_bytes_before)} &rarr; {_fmt_bytes(t.size_bytes_after)}</td>
                    <td style="font-size:12px;line-height:1.45;">{"<br>".join(details)}</td>
                </tr>"""
            )

        floor_pills = "".join(
            f'<span style="display:inline-block;margin:3px 6px 3px 0;padding:4px 10px;border-radius:8px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;font-size:12px;font-weight:600;">{html.escape(lbl)}: {cnt} узл.</span>'
            for lbl, cnt in sorted(city.floor_distribution_by_required_pressure.items())
        )
        floor_block = (
            f'<div style="margin:12px 0 16px 0;"><strong>Распределение конечных узлов по этажности (H<sub>треб</sub> = 10 + 4(n&minus;1) м):</strong><div style="margin-top:6px;">{floor_pills}</div></div>'
            if floor_pills
            else ""
        )

        city_sections.append(
            f"""
            <section style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:22px;margin-bottom:24px;box-shadow:0 1px 3px rgba(15,23,42,0.04);">
                <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:12px;border-bottom:1px solid #f1f5f9;padding-bottom:12px;margin-bottom:14px;">
                    <h2 style="margin:0;font-size:19px;color:#0f172a;">Модель города: {html.escape(city.city_name)}</h2>
                    <span style="font-size:13px;color:#475569;">
                        Время проверки: <strong>{city.elapsed_ms:.1f} мс</strong> &bull;
                        Объём CSV: <strong>{_fmt_bytes(city.size_bytes_before)} &rarr; {_fmt_bytes(city.size_bytes_after)}</strong> (&minus;{city.bytes_saved_pct}%) &bull;
                        Нарушений префиксов ID: <strong>{city.id_prefix_violations_count}</strong> &bull;
                        Графиков != 24 ч: <strong>{len(city.schedule_non_24h_ids)}</strong>
                    </span>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:14px;">
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;">
                        <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Узел (без H<sub>треб</sub>)</div>
                        <div style="font-size:18px;font-weight:700;color:#0f172a;">{city.pruned_transit_nodes_count} строк</div>
                    </div>
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;">
                        <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Поток Насос (все R=0)</div>
                        <div style="font-size:18px;font-weight:700;color:#0f172a;">{city.pruned_standby_pumps_count} строк</div>
                    </div>
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;">
                        <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Потребители Узел (Q=0)</div>
                        <div style="font-size:18px;font-weight:700;color:#0f172a;">{city.pruned_zero_consumers_count} строк</div>
                    </div>
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;">
                        <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Потребление Узел (все R=0)</div>
                        <div style="font-size:18px;font-weight:700;color:#0f172a;">{city.pruned_zero_demand_matrix_rows_count} строк</div>
                    </div>
                </div>
                {floor_block}
                <div style="overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;font-size:13px;">
                        <thead>
                            <tr style="background:#f8fafc;color:#334155;text-align:left;border-bottom:2px solid #e2e8f0;">
                                <th style="padding:9px 8px;">Таблица</th>
                                <th style="padding:9px 8px;">Статус</th>
                                <th style="padding:9px 8px;text-align:right;">Строк (до &rarr; после)</th>
                                <th style="padding:9px 8px;text-align:right;">Удалено</th>
                                <th style="padding:9px 8px;text-align:right;">Полностью 0</th>
                                <th style="padding:9px 8px;text-align:right;">Частично 0</th>
                                <th style="padding:9px 8px;text-align:right;">Пустых null</th>
                                <th style="padding:9px 8px;text-align:right;">Размер</th>
                                <th style="padding:9px 8px;">Детали проверки нулей и колонок</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(rows_html)}
                        </tbody>
                    </table>
                </div>
            </section>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Аудит и очистка нулевых значений выгрузок AquaBit</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f1f5f9;
    color: #0f172a;
    margin: 0;
    padding: 28px;
    line-height: 1.5;
  }}
  .container {{ max-width: 1380px; margin: 0 auto; }}
  td {{ padding: 9px 8px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
  code {{ background: #e2e8f0; padding: 1px 5px; border-radius: 4px; font-size: 11.5px; }}
</style>
</head>
<body>
<div class="container">
  <header style="background:linear-gradient(135deg,#0f172a,#1e3a8a);color:#ffffff;border-radius:14px;padding:26px 30px;margin-bottom:24px;">
    <div style="display:inline-block;padding:4px 10px;border-radius:999px;background:rgba(255,255,255,0.16);font-size:11px;font-weight:700;letter-spacing:0.04em;margin-bottom:10px;">
      {html.escape(mode_badge)} &bull; ADR-0008
    </div>
    <h1 style="margin:0 0 8px 0;font-size:24px;">Проверка файлов AquaBit на нулевые значения и очистка 4 таблиц</h1>
    <p style="margin:0;color:#cbd5e1;font-size:14px;">
      Целевые таблицы очистки: <strong>Поток Насос</strong>, <strong>Потребители Узел</strong>, <strong>Потребление Узел</strong> и <strong>Узел</strong> (где не задано Требуемое давление). Пустые значения (<code>null</code>) строго отделены от <code>0.0</code> (Принцип 6).
    </p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-top:20px;">
      <div style="background:rgba(255,255,255,0.1);padding:12px 16px;border-radius:10px;">
        <div style="font-size:12px;color:#cbd5e1;">Проверено городов</div>
        <div style="font-size:22px;font-weight:700;">{report.cities_count}</div>
      </div>
      <div style="background:rgba(255,255,255,0.1);padding:12px 16px;border-radius:10px;">
        <div style="font-size:12px;color:#cbd5e1;">Исходный объём CSV</div>
        <div style="font-size:22px;font-weight:700;">{_fmt_bytes(report.size_bytes_before)}</div>
      </div>
      <div style="background:rgba(255,255,255,0.1);padding:12px 16px;border-radius:10px;">
        <div style="font-size:12px;color:#cbd5e1;">После удаления нулевых строк</div>
        <div style="font-size:22px;font-weight:700;color:#86efac;">{_fmt_bytes(report.size_bytes_after)} (&minus;{report.bytes_saved_pct}%)</div>
      </div>
      <div style="background:rgba(255,255,255,0.1);padding:12px 16px;border-radius:10px;">
        <div style="font-size:12px;color:#cbd5e1;">Удалено нулевых строк</div>
        <div style="font-size:22px;font-weight:700;color:#fde047;">{report.total_rows_removed}</div>
      </div>
    </div>
  </header>

  <section style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:16px 20px;margin-bottom:24px;font-size:13.5px;color:#78350f;">
    <strong>Справочная верификация формулы скорости по книге Walski et al. (<em>Advanced Water Distribution Modeling and Management</em>, Haestad Press, Ch. 2, p. 40, Eq. 2.9):</strong><br>
    Средняя скорость потока в напорном трубопроводе круглого сечения равна отношению расхода к <strong>площади живого сечения</strong> (а не линейно к диаметру <code>Q / D</code>):
    <code>V = Q / A = 4Q / (&pi;D&sup2;)</code>. Для размерностей AquaBit (<code>Q</code> в м&sup3;/ч, <code>D</code> в мм):
    <code>V [м/с] = 4 &middot; (Q / 3600) / (&pi; &middot; (D / 1000)&sup2;) &approx; 353.67765 &middot; |Q| / D&sup2;</code>.
    Согласно Принципу 1 расчёт гидравлической скорости остаётся на стороне расчётного ядра AquaBit.
  </section>

  {''.join(city_sections)}
</div>
</body>
</html>
"""


def write_zero_audit_reports(
    report: CorpusZeroAuditResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Сохраняет JSON, Markdown и автономный HTML-отчёт проверки/очистки нулей."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "zero_audit_report.json"
    md_path = out / "zero_audit_report.md"
    html_path = out / "zero_audit_report.html"

    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_zero_audit_markdown(report), encoding="utf-8")
    html_path.write_text(render_zero_audit_html(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path, "html": html_path}
