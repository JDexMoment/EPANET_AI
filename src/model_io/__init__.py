"""Чтение моделей EPANET-семейства в едином виде.

Поддерживаемые форматы:
  * `.inp`    — текстовый формат EPANET (в т.ч. экспорт AquaBit, обычно cp1251);
  * `.epanet` — то же самое (иногда zip-архив с .inp внутри);
  * `.net`    — бинарный формат EPANET 2 с маркером `<EPANET2>` (декодируются даже
                10-байтные числа Delphi Extended).

Зачем: приложение-ассистент принимает модель в любом из этих форматов, а вся логика
(параметры, проверка чисел, графики, отчёты) работает с единым словарём секций.

Основной код разбора — вендорные модули EPANET-Model-Cleaner (MIT, см.
`vendor/emc/NOTICE.md`). Здесь — тонкий фасад и аккуратная работа с кодировками.

Пример:
    from src import model_io
    model = model_io.read_model("модель для ИИ — копия.txt")
    model.fmt            # 'inp' | 'net' | 'epanet' | 'zip'
    model.sections["PIPES"]   # список строк
    model_io.write_plain_inp("out.inp", model)
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .vendor.emc import ParserFactory
from .vendor.emc.extract.net_parser import NetParser

SUPPORTED_SUFFIXES = {".inp", ".net", ".epanet", ".txt", ".digwater", ".zip"}


@dataclass
class ModelData:
    """Единое представление модели: секции, порядок, преамбула, формат-источник."""

    sections: dict[str, list[str]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)
    fmt: str = "inp"
    source: str = ""

    def rows(self, section: str) -> list[str]:
        """Строки секции без пустых и комментариев (имя секции — без скобок)."""
        out = []
        for line in self.sections.get(section.upper(), []):
            s = line.strip()
            if s and not s.startswith(";"):
                out.append(s)
        return out

    def count(self, section: str) -> int:
        return len(self.rows(section))


def _decode_text(path: Path) -> str:
    """Текст .inp в правильной кодировке: UTF-8 (с BOM) → cp1251 (AquaBit пишет так)."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", errors="replace")


def _parse_sections(text: str) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Разбор текста .inp на секции. Ключи — ВЕРХНИЙ РЕГИСТР (как у вендорного EMC)."""
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    preamble: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and "]" in s:
            current = s[1: s.index("]")].strip().upper()      # имя секции без скобок
            if current not in sections:
                sections[current] = []
                order.append(current)
            continue
        if current is None:
            if s:
                preamble.append(s)
        else:
            sections[current].append(line.rstrip("\r\n"))
    return sections, order, preamble


def read_model(path: str | Path) -> ModelData:
    """Читает модель любого поддерживаемого формата в единое представление."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"файл модели не найден: {p}")

    # zip-архив (некоторые .epanet приходят архивом)
    if zipfile.is_zipfile(p):
        parser = ParserFactory.create(str(p))
        sections, order = parser.read()
        return ModelData(sections, order, list(parser.get_preamble()), "zip", str(p))

    head = p.read_bytes()[:512]

    # бинарный .NET (EPANET 2)
    if b"<EPANET2>" in head:
        parser = NetParser(str(p))
        sections, order = parser.read()
        return ModelData(sections, order, list(parser.get_preamble()), "net", str(p))

    # текстовые форматы
    text = _decode_text(p)
    sections, order, preamble = _parse_sections(text)
    if not order:
        raise ValueError(f"в файле {p.name} не найдено ни одной секции '[…]'")
    fmt = "epanet" if p.suffix.lower() == ".epanet" else "inp"
    return ModelData(sections, order, preamble, fmt, str(p))


def write_plain_inp(path: str | Path, model: ModelData) -> Path:
    """Записывает модель обычным текстовым .inp (UTF-8) — годна для WNTR и наших утилит."""
    target = Path(path)
    lines: list[str] = []
    lines.extend(model.preamble)
    for name in model.order:
        lines.append("")
        lines.append(name if name.startswith("[") else f"[{name}]")
        lines.extend(model.sections.get(name, []))
    lines.append("")
    lines.append("[END]")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def load_sections(path: str | Path) -> tuple[dict[str, list[str]], str]:
    """Совместимость со старым кодом: {имя_секции_lower: [строки]} + метка источника."""
    model = read_model(path)
    sections = {name.strip("[]").lower(): [l for l in rows if l.strip()]
                for name, rows in model.sections.items()}
    return sections, ("binary/net" if model.fmt == "net" else "text")


__all__ = ["ModelData", "read_model", "write_plain_inp", "load_sections", "SUPPORTED_SUFFIXES"]
