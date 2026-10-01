from datetime import datetime
from pathlib import Path
from typing import Tuple
from ai_module.config.settings import REPORTS_OUTPUT_DIR
from ai_module.context.schemas import LLMContextPayload


class ReportGenerator:
    """
    Report Generator (Roadmap Section 4).
    Generates structured engineering reports (Markdown & HTML) keeping
    deterministic EPANET facts and AI commentary strictly separated.
    """

    @staticmethod
    def save_report(context: LLMContextPayload, ai_commentary: str) -> Tuple[str, str]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in context.project.name)
        md_path = REPORTS_OUTPUT_DIR / f"report_{safe_name}_{ts}.md"
        html_path = REPORTS_OUTPUT_DIR / f"report_{safe_name}_{ts}.html"

        kpi = context.kpi
        net = context.network_summary
        an = context.analysis

        alerts_rows = []
        for idx, a in enumerate(context.alerts, 1):
            alerts_rows.append(
                f"| {idx} | `{a.severity.upper()}` | `{a.object_type}` | **{a.object}** | "
                f"`{a.metric_name}` | **{a.value} {a.unit}** | `{a.threshold} {a.unit}` | {a.description} |"
            )
        alerts_table = (
            "| № | Уровень | Тип объекта | ID | Параметр | Значение | Порог | Описание |\n"
            "|---|---------|-------------|----|----------|----------|-------|----------|\n"
            + ("\n".join(alerts_rows) if alerts_rows else "| - | INFO | - | - | - | - | - | Нарушений не выявлено |")
        )

        md_content = f"""# ИНЖЕНЕРНЫЙ ОТЧЁТ ПО ГИДРАВЛИЧЕСКОМУ РАСЧЁТУ EPANET 2.2
**Проект:** `{context.project.name}`  
**Сценарий:** `{context.project.scenario}`  
**Дата формирования:** `{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`  

---

## ЧАСТЬ A. ДЕТЕРМИНИРОВАННЫЕ ФАКТЫ РАСЧЁТА (EPANET 2.2 ENGINE & ANALYTICS)
*(Численные значения получены напрямую из гидравлического ядра EPANET 2.2 без участия LLM)*

### 1. Исходные параметры модели
- **Режим расчёта:** `{an.type}` (длительность `{an.duration_h} ч`, шаг `{an.step_h} ч`, расчётный срез `t = {an.active_time_h} ч`)
- **Статус сходимости решателя:** `{an.status}`
- **Состав расчётной схемы:** узлов (`junctions`) — **{net.junctions}**, резервуаров (`reservoirs`) — **{net.reservoirs}**, баков (`tanks`) — **{net.tanks}**, труб (`pipes`) — **{net.pipes}**, насосов (`pumps`) — **{net.pumps}**, клапанов (`valves`) — **{net.valves}**
- **Единицы измерения в отчёте:** `{context.project.normalized_units}` (исходные в проекте: `{context.project.flow_units_native}`)

### 2. Сводные показатели (KPI сети)
| Показатель | Значение | Объект (ID) |
|------------|----------|-------------|
| Минимальный свободный напор | **{kpi.min_pressure_m} м** | `{kpi.min_pressure_node}` |
| Максимальный свободный напор | **{kpi.max_pressure_m} м** | `{kpi.max_pressure_node}` |
| Суммарный водоразбор | **{kpi.total_demand_lps} л/с** | Вся сеть |
| Максимальная скорость потока | **{kpi.max_velocity_mps} м/с** | `{kpi.max_velocity_pipe}` |
| Максимальный удельный уклон | **{kpi.max_headloss_m_per_km} м/км** | `{kpi.max_headloss_pipe}` |
| Выявлено пороговых отклонений | **{kpi.alerts_count}** | - |

### 3. Реестр выявленных отклонений (Top-{len(context.alerts)})
{alerts_table}

---

## ЧАСТЬ B. ИНЖЕНЕРНАЯ ИНТЕРПРЕТАЦИЯ И РЕКОМЕНДАЦИИ (AI MODULE / QWEN3)
*(Сформировано локальной моделью на основании детерминированного JSON-контекста)*

{ai_commentary}
"""
        md_path.write_text(md_content, encoding="utf-8")

        html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Инженерный отчёт EPANET 2.2 — {context.project.name}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 980px; margin: 32px auto; padding: 0 24px; color: #1e293b; line-height: 1.6; }}
  h1 {{ color: #0f172a; border-bottom: 2px solid #0284c7; padding-bottom: 10px; }}
  h2 {{ color: #0369a1; margin-top: 28px; }}
  .box-facts {{ background: #f8fafc; border-left: 4px solid #0284c7; padding: 16px 20px; border-radius: 6px; margin-bottom: 24px; }}
  .box-ai {{ background: #f0fdf4; border-left: 4px solid #16a34a; padding: 16px 20px; border-radius: 6px; white-space: pre-wrap; }}
  table {{ border-collapse: collapse; width: 100%; margin: 14px 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 8px 12px; text-align: left; font-size: 14px; }}
  th {{ background: #e2e8f0; }}
  code {{ background: #e2e8f0; padding: 2px 5px; border-radius: 4px; }}
</style>
</head>
<body>
  <h1>ИНЖЕНЕРНЫЙ ОТЧЁТ ПО ГИДРАВЛИЧЕСКОМУ РАСЧЁТУ EPANET 2.2</h1>
  <p><b>Проект:</b> <code>{context.project.name}</code> | <b>Срез времени:</b> <code>t = {an.active_time_h} ч</code> | <b>Статус:</b> <code>{an.status}</code></p>
  <div class="box-facts">
    <h2>ЧАСТЬ A. ДЕТЕРМИНИРОВАННЫЕ ФАКТЫ РАСЧЁТА (EPANET ENGINE)</h2>
    <p><b>Узлов:</b> {net.junctions} | <b>Труб:</b> {net.pipes} | <b>Насосов:</b> {net.pumps} | <b>Резервуаров и баков:</b> {net.reservoirs + net.tanks}</p>
    <table>
      <tr><th>Показатель KPI</th><th>Значение</th><th>Объект</th></tr>
      <tr><td>Минимальный свободный напор</td><td><b>{kpi.min_pressure_m} м</b></td><td><code>{kpi.min_pressure_node}</code></td></tr>
      <tr><td>Максимальный свободный напор</td><td><b>{kpi.max_pressure_m} м</b></td><td><code>{kpi.max_pressure_node}</code></td></tr>
      <tr><td>Суммарный водоразбор</td><td><b>{kpi.total_demand_lps} л/с</b></td><td>Вся сеть</td></tr>
      <tr><td>Максимальная скорость потока</td><td><b>{kpi.max_velocity_mps} м/с</b></td><td><code>{kpi.max_velocity_pipe}</code></td></tr>
      <tr><td>Максимальный удельный уклон</td><td><b>{kpi.max_headloss_m_per_km} м/км</b></td><td><code>{kpi.max_headloss_pipe}</code></td></tr>
    </table>
  </div>
  <h2>ЧАСТЬ B. ИНЖЕНЕРНАЯ ИНТЕРПРЕТАЦИЯ И РЕКОМЕНДАЦИИ (AI MODULE)</h2>
  <div class="box-ai">{ai_commentary}</div>
</body>
</html>"""
        html_path.write_text(html_content, encoding="utf-8")
        return str(md_path), str(html_path)
