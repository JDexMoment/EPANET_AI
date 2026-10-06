import copy
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class InpParser:
    """
    Парсер INP-файлов EPANET.
    Читает файл, разбивает на секции и сохраняет порядок следования.
    Поддерживает расширения: .inp, .net, .epanet
    """

    SUPPORTED_EXTENSIONS = {'.inp', '.net', '.epanet'}

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self._sections: Dict[str, List[str]] = {}
        self._section_order: List[str] = []
        self._preamble: List[str] = []
        self._is_parsed: bool = False

    @staticmethod
    def is_supported(filepath: str) -> bool:
        """Проверяет, поддерживается ли расширение файла."""
        return Path(filepath).suffix.lower() in InpParser.SUPPORTED_EXTENSIONS

    def read(self) -> Tuple[Dict[str, List[str]], List[str]]:
        """
        Читает файл модели и разбивает его на секции.

        Returns:
            Кортеж (словарь секций, список порядка секций)

        Raises:
            FileNotFoundError: если файл не найден
            ValueError: если расширение не поддерживается
        """
        if not self.filepath.exists():
            raise FileNotFoundError(f"Файл модели не найден: {self.filepath}")

        if not self.is_supported(str(self.filepath)):
            raise ValueError(
                f"Формат '{self.filepath.suffix}' не поддерживается. "
                f"Допустимые: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )

        self._sections.clear()
        self._section_order.clear()
        self._preamble.clear()

        current_section: Optional[str] = None

        with open(self.filepath, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                stripped_line = line.strip()

                if stripped_line.startswith('[') and ']' in stripped_line:
                    bracket_end = stripped_line.index(']') + 1
                    current_section = stripped_line[:bracket_end].upper()

                    if current_section not in self._sections:
                        self._sections[current_section] = []
                        self._section_order.append(current_section)

                else:
                    raw_line = line.rstrip('\n').rstrip('\r')

                    if current_section:
                        self._sections[current_section].append(raw_line)
                    else:
                        if stripped_line:
                            self._preamble.append(raw_line)

        self._is_parsed = True
        return self._sections, self._section_order

    def get_preamble(self) -> List[str]:
        """Возвращает строки, идущие до первой секции."""
        return list(self._preamble)

    def get_sections_copy(self) -> Dict[str, List[str]]:
        """Возвращает глубокую копию секций."""
        return copy.deepcopy(self._sections)

    def get_order_copy(self) -> List[str]:
        """Возвращает копию порядка секций."""
        return list(self._section_order)