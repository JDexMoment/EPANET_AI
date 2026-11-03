"""Рендеринг автономного диагностического HTML-отчёта при fatal на валидации (§4 Этап 2, §5.7)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from aquabit_ai.config.manifest import ManifestOutSchema
from aquabit_ai.config.validation_models import ValidationReport


def _default_templates_dir() -> Path:
    repo_templates = Path(__file__).resolve().parents[3] / "templates"
    if repo_templates.is_dir():
        return repo_templates
    raise FileNotFoundError(f"Директория шаблонов Jinja2 не найдена: {repo_templates}")


def render_fatal_diagnostic_html(
    manifest_out: ManifestOutSchema,
    validation_report: ValidationReport,
    output_dir: Path,
    templates_dir: Path | None = None,
) -> Path:
    """Рендерит автономный report.html с диагностикой ошибок валидации (без вызова ИИ)."""
    tpl_dir = templates_dir or _default_templates_dir()
    env = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}

    template = env.get_template("validation_fatal.html.j2")
    html_text = template.render(
        manifest_out=manifest_out.model_dump(mode="json"),
        validation_report=validation_report.model_dump(mode="json"),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    report_path.write_text(html_text, encoding="utf-8")
    return report_path
