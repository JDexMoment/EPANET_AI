"""Приём файла модели в любом формате → чистый .inp.

Использует вендорные ETL-модули EPANET-Model-Cleaner (.inp, .NET, .epanet, zip-архивы).
Если апстрим недоступен, для .inp работает простой путь «как есть» — сервис продолжает
принимать хотя бы текстовый формат.
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from . import config

try:                                        # вендорная копия ETL
    from .vendor.emc import InpCleaner, ModelWriter, ParserFactory
    EMC_AVAILABLE = True
except Exception as _e:                     # noqa: BLE001
    EMC_AVAILABLE = False
    EMC_ERROR = str(_e)


class ConversionError(RuntimeError):
    pass


def sniff_format(path: Path) -> str:
    """Определяет реальный формат по содержимому, а не по расширению."""
    ext = path.suffix.lower()
    try:
        head = path.read_bytes()[:1024]
    except OSError:
        return ext.lstrip(".") or "unknown"
    if zipfile.is_zipfile(path):
        return "epanet_zip"
    if b"<EPANET2>" in head:
        return "net"
    text = head.decode("utf-8", errors="ignore")
    if "[JUNCTIONS]" in text or "[PIPES]" in text or "[TITLE]" in text:
        return "inp"
    for enc in ("cp1251", "latin-1"):
        t = head.decode(enc, errors="ignore")
        if "[JUNCTIONS]" in t or "[PIPES]" in t:
            return "inp_cp1251"
    return ext.lstrip(".") or "unknown"


def convert_to_clean_inp(src: Path, out_inp: Path) -> dict:
    """Возвращает отчёт о конвертации: формат, что удалено, сколько секций/строк."""
    fmt = sniff_format(src)
    out_inp.parent.mkdir(parents=True, exist_ok=True)

    if not EMC_AVAILABLE:
        if fmt.startswith("inp"):
            shutil.copyfile(src, out_inp)
            return {"engine": "passthrough", "detected_format": fmt,
                    "note": "EPANET-Model-Cleaner недоступен: файл сохранён без очистки",
                    "sections": None, "removed_sections": []}
        raise ConversionError(
            f"формат «{fmt}» требует EPANET-Model-Cleaner, но модуль не загружен: {EMC_ERROR}")

    try:
        parser = ParserFactory.create(str(src))
        sections, order = parser.read()
        preamble = parser.get_preamble()
        before_lines = sum(len(v) for v in sections.values())

        cleaner = InpCleaner(sections, order)
        clean_sections, clean_order = cleaner.clean(
            remove_comments=True,
            drop_empty_lines=True,
            remove_sections=InpCleaner.DEFAULT_REMOVE_SECTIONS,
            preserve_title_comments=True,
        )
        ModelWriter(str(out_inp)).write(clean_sections, clean_order, preamble)
        after_lines = sum(len(v) for v in clean_sections.values())
        return {
            "engine": "EPANET-Model-Cleaner (vendored)",
            "detected_format": fmt,
            "parser": type(parser).__name__,
            "sections": len(clean_sections),
            "section_names": sorted(clean_sections.keys()),
            "removed_sections": [s for s in InpCleaner.DEFAULT_REMOVE_SECTIONS if s.strip("[]") not in
                                 [x.strip("[]") for x in clean_sections]],
            "lines_before": before_lines,
            "lines_after": after_lines,
            "lines_removed": before_lines - after_lines,
            "note": "удалены графические секции (BACKDROP, TAGS, LABELS), комментарии и пустые строки",
        }
    except ConversionError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ConversionError(f"не удалось прочитать «{fmt}» файл: {type(e).__name__}: {e}") from e


def inline_zip_inp(src: Path, workdir: Path) -> Path | None:
    """Если пришёл zip (.epanet-архив или просто zip с моделью) — достаём из него .inp/.net."""
    if not zipfile.is_zipfile(src):
        return None
    workdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        for cand in sorted(names, key=len):
            if Path(cand).suffix.lower() in (".inp", ".net", ".epanet"):
                z.extract(cand, workdir)
                return workdir / cand
    return None
