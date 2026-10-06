import re
import copy
from typing import Dict, List, Tuple, Optional


class InpCleaner:
    """
    Очиститель содержимого INP-файла.
    Работает с копиями данных — не мутирует исходные структуры.
    """

    DEFAULT_REMOVE_SECTIONS = [
        "BACKDROP",
        "TAGS",
        "LABELS",
    ]

    def __init__(self, sections: Dict[str, List[str]], section_order: List[str]):
        self._sections: Dict[str, List[str]] = copy.deepcopy(sections)
        self._section_order: List[str] = list(section_order)

    def clean(
        self,
        remove_comments: bool = True,
        drop_empty_lines: bool = True,
        remove_sections: Optional[List[str]] = None,
        preserve_title_comments: bool = True,
    ) -> Tuple[Dict[str, List[str]], List[str]]:
        """
        Выполняет очистку данных.

        Args:
            remove_comments: удалять комментарии (текст после ;)
            drop_empty_lines: удалять пустые строки
            remove_sections: список секций для полного удаления
            preserve_title_comments: сохранять содержимое секции [TITLE]

        Returns:
            Кортеж (очищенные секции, порядок секций)
        """
        if remove_sections is None:
            remove_sections = []

        self._remove_unwanted_sections(remove_sections)

        for section_name in list(self._sections.keys()):
            if preserve_title_comments and section_name == "[TITLE]":
                continue

            if section_name == "[END]":
                continue

            raw_lines = self._sections[section_name]
            cleaned_lines = []

            for line in raw_lines:
                processed_line = line

                if remove_comments:
                    processed_line = self._strip_comment(processed_line)

                processed_line = processed_line.strip()

                if drop_empty_lines:
                    if processed_line:
                        cleaned_lines.append(processed_line)
                else:
                    cleaned_lines.append(processed_line)

            self._sections[section_name] = cleaned_lines

        self._remove_empty_sections()

        return self._sections, self._section_order

    def _strip_comment(self, line: str) -> str:
        """Удаляет комментарий из строки (всё после ;)."""
        return re.sub(r';.*$', '', line)

    def _remove_unwanted_sections(self, remove_list: List[str]):
        """Удаляет указанные секции из данных и из порядка."""
        formatted = set()
        for name in remove_list:
            normalized = name.strip().upper()
            if not normalized.startswith('['):
                normalized = f"[{normalized}]"
            formatted.add(normalized)

        for sec_name in formatted:
            if sec_name in self._sections:
                del self._sections[sec_name]
            if sec_name in self._section_order:
                self._section_order.remove(sec_name)

    def _remove_empty_sections(self):
        """Удаляет секции, в которых не осталось строк после очистки."""
        empty_sections = [
            name for name, lines in self._sections.items()
            if not lines and name != "[END]"
        ]
        for sec_name in empty_sections:
            del self._sections[sec_name]
            if sec_name in self._section_order:
                self._section_order.remove(sec_name)