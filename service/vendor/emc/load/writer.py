import os
import zipfile
import tempfile
from pathlib import Path
from typing import Dict, List, Optional


class ModelWriter:
    """
    Универсальный класс для сохранения моделей EPANET.
    Поддерживает сохранение в форматах .INP, .NET и .EPANET.
    """

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)

    def write(
            self,
            sections: Dict[str, List[str]],
            section_order: List[str],
            preamble: Optional[List[str]] = None,
    ):
        ext = self.filepath.suffix.lower()

        try:
            if ext == '.epanet':
                self._write_epanet_archive(sections, section_order, preamble)
            else:
                # Для .inp и .net пишем обычный текст
                self._write_plain_text(self.filepath, sections, section_order, preamble)

            print(f"[Writer] Файл успешно сохранен: {self.filepath}")

        except IOError as e:
            print(f"[Writer] Ошибка записи файла: {e}")
            raise

    def _write_plain_text(
            self,
            target_path: Path,
            sections: Dict[str, List[str]],
            section_order: List[str],
            preamble: Optional[List[str]] = None,
    ):
        """Записывает модель в виде классического текстового файла INP."""
        with open(target_path, 'w', encoding='utf-8') as f:
            # 1. Запись преамбулы
            if preamble:
                for line in preamble:
                    f.write(f"{line}\n")
                f.write("\n")

            # 2. Запись секций
            for section_name in section_order:
                if section_name not in sections:
                    continue

                lines = sections[section_name]

                f.write(f"{section_name}\n")
                for line in lines:
                    # В EPANET строки данных часто пишутся с небольшим отступом для красоты
                    f.write(f" {line}\n")
                f.write("\n")

            # 3. Маркер конца
            if "[END]" not in section_order:
                f.write("[END]\n")

    def _write_epanet_archive(
            self,
            sections: Dict[str, List[str]],
            section_order: List[str],
            preamble: Optional[List[str]] = None,
    ):
        """
        Формат .epanet часто представляет собой ZIP-архив.
        Мы создаем текстовый INP-файл и запаковываем его в архив.
        """
        # Создаем временный файл INP
        with tempfile.NamedTemporaryFile(suffix='.inp', delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            # Записываем данные во временный файл
            self._write_plain_text(tmp_path, sections, section_order, preamble)

            # Создаем ZIP-архив с расширением .epanet
            with zipfile.ZipFile(self.filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Внутри архива файл обычно называется по имени проекта или просто model.inp
                internal_name = f"{self.filepath.stem}.inp"
                zf.write(tmp_path, arcname=internal_name)

        finally:
            # Удаляем временный файл
            if tmp_path.exists():
                os.remove(tmp_path)

    def to_string(
            self,
            sections: Dict[str, List[str]],
            section_order: List[str],
            preamble: Optional[List[str]] = None,
    ) -> str:
        """Формирует содержимое файла как строку (для вывода на экран)."""
        result_lines: List[str] = []

        if preamble:
            result_lines.extend(preamble)
            result_lines.append("")

        for section_name in section_order:
            if section_name not in sections:
                continue

            result_lines.append(section_name)
            result_lines.extend([f" {line}" for line in sections[section_name]])
            result_lines.append("")

        if "[END]" not in section_order:
            result_lines.append("[END]")

        return "\n".join(result_lines)