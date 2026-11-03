"""Генератор инженерных отчётов (JSON, Markdown, автономный HTML) по оптимизации выгрузки AquaBit (ADR-0007)."""

from __future__ import annotations

import html
import json
from pathlib import Path

from aquabit_ai.profile.analyzer import CorpusExportProfile


TIER_LABELS_RU: dict[str, tuple[str, str]] = {
    "KEEP_AND_ENRICH": ("ЯДРО: ОСТАВИТЬ И ОБОГАТИТЬ", "#15803d"),
    "DOWNSAMPLE_60X_TO_HOURLY": ("СЖАТЬ В 50–60× (ЧАСОВОЙ ШАГ + MIN/MAX)", "#1d4ed8"),
    "MERGE_EQUIPMENT_REGIMES": ("ОБЪЕДИНИТЬ В РЕЖИМЫ ОБОРУДОВАНИЯ", "#b45309"),
    "DROP_REDUNDANT": ("ИСКЛЮЧИТЬ ИЗ ВЫГРУЗКИ (100% ДУБЛЬ)", "#b91c1c"),
}


def _fmt_bytes(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} МБ"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} КБ"
    return f"{num_bytes} Б"


def render_export_optimization_markdown(profile: CorpusExportProfile) -> str:
    """Формирует подробное инженерное ТЗ в формате Markdown для разработчика AquaBit."""
    lines: list[str] = [
        "# Аудит информативности 13 CSV-таблиц AquaBit и план оптимизации экспорта/импорта",
        "",
        f"- **Проанализировано городов / моделей:** `{profile.cities_count}`",
        f"- **Суммарный текущий объём:** `{_fmt_bytes(profile.total_bytes)}` (доля 5 широких матриц `R0..R1439`: **`{profile.wide_bytes_share_pct}%`**)",
        f"- **Доля избыточных байт (нули + 60× линейная передискретизация + дубль спроса):** **`{profile.redundant_bytes_pct}%`** (`{_fmt_bytes(profile.redundant_bytes_total)}`)",
        f"- **Прогноз после перехода на часовой шаг `H0..H23 + min/max` и удаления `Потребление Узел.csv`:** **`-{profile.savings_hourly_pct}%`**",
        f"- **Прогноз при переходе на компактный экспорт v2 (агрегаты + ключевые профили / Parquet):** **`-{profile.savings_compact_v2_pct}%`**",
        "",
        "## 1. Главные закономерности и найденные ошибки выгрузки",
        "",
    ]

    for idx, finding in enumerate(profile.global_findings, start=1):
        lines.append(f"{idx}. {finding}")
    lines.append("")

    lines.extend(
        [
            "## 2. Матрица решений по 13 таблицам (что оставить, что сжать, что убрать)",
            "",
            "| Файл выгрузки | Внутренний маршрут | Доля объёма | Нулевые строки | Погр. часовой интерп. (P99) | Ценность (0–100) | Решение для разработчика AquaBit |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )

    for item in profile.table_tier_summary:
        tier_ru, _ = TIER_LABELS_RU.get(item["action_tier"], (item["action_tier"], "#334155"))
        p99_str = (
            f"{item['max_hourly_p99_interp_err']:.4f}"
            if item["max_hourly_p99_interp_err"] is not None
            else "—"
        )
        zero_str = f"{item['avg_all_zero_rows_pct']:.1f}%" if item["is_wide_timeseries"] else "—"
        lines.append(
            f"| `{item['example_source_file']}` | `{item['canonical_path']}` | "
            f"{item['share_of_corpus_bytes_pct']:.2f}% | {zero_str} | {p99_str} | "
            f"**{item['signal_score_0_100']}** | **{tier_ru}** — {item['developer_verdict']} |"
        )
    lines.append("")

    lines.extend(
        [
            "## 3. Детализация по каждому городу",
            "",
        ]
    )

    for city in profile.cities:
        lines.extend(
            [
                f"### Город: `{city.city_name}` (`{_fmt_bytes(city.total_bytes)}`, {city.n_files} файлов, {city.n_steps} шагов по {city.step_seconds} с)",
                "",
                f"- **Строгая валидация Этапа 2:** `{city.validation_status_strict}`",
                f"- **Петли `Начало == Конец` (`SELF_LOOP_LINK`):** `{city.self_loop_links_count}` шт."
                + (
                    " *(КРИТИЧЕСКИЙ БАГ СЕРИАЛИЗАЦИИ `'c' + link_id` ПОДТВЕРЖДЁН!)*"
                    if city.exporter_own_id_cast_bug_detected
                    else ""
                ),
                f"- **Осиротевшие ссылки (`ORPHAN_REFERENCE`):** `{city.orphan_references_count}` шт.",
                f"- **Неполные Q-H кривые насосов (<3 точек):** `{city.incomplete_pump_curves_count}` шт.",
                f"- **Константные графики потребления (`Данные=1`):** `{city.constant_patterns_count}/{city.total_patterns_count}`",
            ]
        )
        if city.demand_redundancy.present:
            lines.append(f"- **Аудит `Потребление Узел.csv`:** {city.demand_redundancy.explanation}")
        if city.missing_high_value_features:
            lines.append("- **Недостающие важные гидравлические признаки:**")
            for mf in city.missing_high_value_features:
                lines.append(f"  - {mf}")
        lines.append("")

    lines.extend(
        [
            "## 4. Рекомендуемая целевая схема экспорта AquaBit v2 (сокращение с 13 до 9 компактных файлов, уменьшение объёма в 25–50 раз)",
            "",
            "1. **`manifest.json`** *(новый, ~1 КБ)*: версия AquaBit, `step_seconds`, `converged`, формула потерь, единицы измерения.",
            "2. **`Узел.csv`** *(обогатить)*: `ID,Название,Высота_m,Требуемое_давление_m,Мин_напор_m,Макс_напор_m,Мин_свободный_напор_m,Макс_свободный_напор_m,Часов_ниже_нормы`.",
            "3. **`Труба.csv`** *(исправить топологию + обогатить)*: `ID,Название,Начало,Конец,Диаметр_mm,Длина_m,Шероховатость_mm,Малые_потери,Мин_поток_m3_h,Макс_поток_m3_h,Макс_скорость_m_s,Смен_направления`.",
            "4. **`Источники.csv` + `Резервуар.csv`**: добавить `Название`, `Узел`, граничный напор/уровни `min/max/init`.",
            "5. **`Насос.csv` + `Клапан.csv`** *(исправить `Начало,Конец`)*: добавить `Название`, номинальный режим/статус, min/max поток и напор.",
            "6. **`Кривая QH.csv`**: `ID,flow_m3_h,head_m` (не менее 3 точек на каждую кривую `u*`).",
            "7. **`Потребители Узел.csv` + `График потребления.csv`**: `node_id,base_demand_m3_h,curve_id` и `curve_id,step_index,multiplier` — **полностью заменяют гигантский `Потребление Узел.csv`!**",
            "8. **`Динамика_24ч` (`Напор Узел`, `Поток Труба`, `Режимы Оборудования`)**: выгружать **24 часовых среза `H0..H23`** вместо 1 440 линейно интерполированных минутных колонок `R0..R1439` (либо Zstd Parquet), исключая полностью нулевые строки резервного оборудования.",
            "",
        ]
    )

    return "\n".join(lines)


def render_export_optimization_html(profile: CorpusExportProfile) -> str:
    """Рендерит автономный (без внешних ресурсов) HTML-дашборд аудита информативности таблиц."""
    esc = html.escape

    findings_html = "".join(
        f"<li>{esc(item)}</li>" for item in profile.global_findings
    )

    rows_html_parts: list[str] = []
    for item in profile.table_tier_summary:
        tier_ru, badge_color = TIER_LABELS_RU.get(
            item["action_tier"], (item["action_tier"], "#334155")
        )
        share = float(item["share_of_corpus_bytes_pct"])
        bar_w = max(2.0, min(100.0, share))
        zero_str = f"{item['avg_all_zero_rows_pct']:.1f}%" if item["is_wide_timeseries"] else "—"
        p99_str = (
            f"{item['max_hourly_p99_interp_err']:.4f}"
            if item["max_hourly_p99_interp_err"] is not None
            else "—"
        )
        score = int(item["signal_score_0_100"])
        score_color = "#15803d" if score >= 85 else ("#b45309" if score >= 50 else "#b91c1c")
        rows_html_parts.append(
            f"""
            <tr>
              <td><strong>{esc(item['example_source_file'])}</strong><br><span class="muted">{esc(item['canonical_path'])}</span></td>
              <td>
                <div><strong>{share:.2f}%</strong> ({esc(_fmt_bytes(item['total_bytes']))})</div>
                <div class="bar-track"><div class="bar-fill" style="width:{bar_w:.1f}%;"></div></div>
              </td>
              <td class="num">{zero_str}</td>
              <td class="num">{p99_str}</td>
              <td class="num"><span class="score-pill" style="background:{score_color};">{score}/100</span></td>
              <td>
                <span class="tier-badge" style="background:{badge_color};">{esc(tier_ru)}</span>
                <div class="verdict-text">{esc(item['developer_verdict'])}</div>
              </td>
            </tr>
            """
        )

    cities_cards: list[str] = []
    for city in profile.cities:
        bug_alert = (
            f'<div class="alert-bug">КРИТИЧЕСКИЙ БАГ ТОПОЛОГИИ: {city.self_loop_links_count} участков с '
            "Начало == Конец ('c' + ID самого участка, напр. e702 &rarr; c702,c702). Топология сети разрушена при сериализации!</div>"
            if city.self_loop_links_count > 0
            else ""
        )
        missing_li = "".join(f"<li>{esc(m)}</li>" for m in city.missing_high_value_features)
        file_mini_rows = "".join(
            f"""
            <tr>
              <td>{esc(f.source_file)}</td>
              <td class="num">{esc(_fmt_bytes(f.size_bytes))} ({f.share_of_city_bytes_pct:.1f}%)</td>
              <td class="num">{f.rows} &times; {f.columns}</td>
              <td class="num">{f"{f.all_zero_rows_pct:.1f}%" if f.is_wide_timeseries else "—"}</td>
              <td class="num">{f"{f.quasi_constant_rows_pct:.1f}%" if f.is_wide_timeseries else "—"}</td>
              <td class="num">{f"{f.hourly_interp_max_abs_err:.4f}" if f.hourly_interp_max_abs_err is not None else "—"}</td>
              <td class="num">{f.abrupt_switch_rows_count if f.is_wide_timeseries else "—"}</td>
            </tr>
            """
            for f in city.files
        )
        cities_cards.append(
            f"""
            <section class="card">
              <h2>Город: {esc(city.city_name)} <span class="muted">({esc(_fmt_bytes(city.total_bytes))}, {city.n_files} файлов, {city.n_steps} шагов по {city.step_seconds} с, парсинг {city.total_parse_time_ms:.1f} мс)</span></h2>
              {bug_alert}
              <p><strong>Аудит избыточности спроса:</strong> {esc(city.demand_redundancy.explanation or "Таблица Потребление Узел отсутствует.")}</p>
              <table class="compact-table">
                <thead>
                  <tr>
                    <th>Файл</th>
                    <th>Объём (доля)</th>
                    <th>Размерность</th>
                    <th>Строки из нулей</th>
                    <th>Квазиконст. (&Delta;&le;0.05)</th>
                    <th>Макс. погр. 60-мин интерп.</th>
                    <th>Внутричас. переключений</th>
                  </tr>
                </thead>
                <tbody>{file_mini_rows}</tbody>
              </table>
              <div class="missing-box">
                <strong>Недостающие высокозначимые признаки для гидравлической интерпретации:</strong>
                <ul>{missing_li}</ul>
              </div>
            </section>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>AquaBit AI — Аудит информативности 13 таблиц и оптимизация экспорта</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f8fafc;
      color: #0f172a;
      margin: 0;
      padding: 24px;
      line-height: 1.5;
    }}
    .container {{ max-width: 1280px; margin: 0 auto; }}
    h1 {{ font-size: 24px; margin: 0 0 8px 0; color: #0f172a; }}
    h2 {{ font-size: 18px; margin: 0 0 12px 0; color: #1e293b; }}
    .subtitle {{ color: #475569; margin-bottom: 20px; font-size: 14px; }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-bottom: 20px;
    }}
    .kpi {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 16px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }}
    .kpi-label {{ font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: 0.04em; }}
    .kpi-val {{ font-size: 26px; font-weight: 700; margin-top: 4px; color: #0f172a; }}
    .kpi-val.good {{ color: #15803d; }}
    .kpi-val.warn {{ color: #b91c1c; }}
    .card {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e2e8f0; padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; font-weight: 600; color: #334155; }}
    .num {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
    .muted {{ color: #64748b; font-size: 12px; font-weight: 400; }}
    .bar-track {{ background: #e2e8f0; height: 7px; border-radius: 4px; margin-top: 5px; overflow: hidden; }}
    .bar-fill {{ background: #2563eb; height: 100%; }}
    .tier-badge {{
      display: inline-block;
      color: #ffffff;
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 4px;
      margin-bottom: 4px;
    }}
    .score-pill {{
      display: inline-block;
      color: #ffffff;
      font-weight: 700;
      font-size: 12px;
      padding: 2px 8px;
      border-radius: 999px;
    }}
    .verdict-text {{ color: #334155; font-size: 12.5px; margin-top: 3px; }}
    .alert-bug {{
      background: #fef2f2;
      border-left: 4px solid #dc2626;
      color: #991b1b;
      padding: 10px 14px;
      border-radius: 6px;
      font-weight: 600;
      margin-bottom: 12px;
      font-size: 13px;
    }}
    .missing-box {{
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-radius: 8px;
      padding: 12px 16px;
      margin-top: 14px;
      font-size: 13px;
    }}
    .missing-box ul {{ margin: 6px 0 0 0; padding-left: 20px; }}
    .compact-table th, .compact-table td {{ padding: 6px 8px; font-size: 12.5px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Аудит информативности 13 таблиц AquaBit и план оптимизации выгрузки</h1>
    <div class="subtitle">Автоматический инженерный профиль объёма, разреженности, 60-кратной передискретизации R0..R1439 и целостности топологии</div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi-label">Городов в выборке</div>
        <div class="kpi-val">{profile.cities_count}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Доля широких матриц R0..R1439</div>
        <div class="kpi-val warn">{profile.wide_bytes_share_pct:.1f}%</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Избыточный объём (нули + линейн. шаг 1 мин)</div>
        <div class="kpi-val warn">{profile.redundant_bytes_pct:.1f}%</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Сжатие: часовой CSV без дубля спроса</div>
        <div class="kpi-val good">&minus;{profile.savings_hourly_pct:.1f}%</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Сжатие: целевой экспорт v2</div>
        <div class="kpi-val good">&minus;{profile.savings_compact_v2_pct:.1f}%</div>
      </div>
    </div>

    <section class="card">
      <h2>Ключевые выводы для разработчика AquaBit</h2>
      <ul>{findings_html}</ul>
    </section>

    <section class="card">
      <h2>Рейтинг информативности и решения по всем таблицам</h2>
      <table>
        <thead>
          <tr>
            <th>Таблица выгрузки</th>
            <th>Доля объёма</th>
            <th>Строки из 0.00</th>
            <th>Погр. 60-мин интерп. (P99)</th>
            <th>Информ. ценность</th>
            <th>Рекомендуемое действие</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows_html_parts)}
        </tbody>
      </table>
    </section>

    {''.join(cities_cards)}
  </div>
</body>
</html>
"""


def write_export_profile_artifacts(
    profile: CorpusExportProfile,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Сохраняет export_profile.json, export_optimization_report.md и export_optimization_report.html."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "export_profile.json"
    md_path = out / "export_optimization_report.md"
    html_path = out / "export_optimization_report.html"

    json_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_export_optimization_markdown(profile), encoding="utf-8")
    html_path.write_text(render_export_optimization_html(profile), encoding="utf-8")

    return {
        "profile_json": json_path,
        "report_markdown": md_path,
        "report_html": html_path,
    }
