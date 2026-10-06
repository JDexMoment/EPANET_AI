import zipfile
import tempfile
from pathlib import Path

from .inp_parser import InpParser
from .net_parser import NetParser


class ParserFactory:
    """Фабрика парсеров. Автоматически определяет реальный формат файла."""

    SUPPORTED_EXTENSIONS = {'.inp', '.net', '.epanet'}

    @staticmethod
    def is_supported(filepath: str) -> bool:
        return Path(filepath).suffix.lower() in ParserFactory.SUPPORTED_EXTENSIONS

    @staticmethod
    def create(filepath: str):
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {filepath}")

        # 1. Проверяем, не является ли это ZIP-архивом
        # (Некоторые программы сохраняют .epanet как zip-архив)
        if zipfile.is_zipfile(filepath):
            return ParserFactory._handle_zip_archive(filepath)

        # Читаем начало файла для определения сигнатуры
        with open(filepath, 'rb') as f:
            header = f.read(512)

        # 2. Проверяем бинарный маркер EPANET (.NET)
        if b'<EPANET2>' in header:
            return NetParser(filepath)

        # 3. Проверяем JSON формат
        try:
            text_header = header.decode('utf-8', errors='ignore').strip()
            if text_header.startswith('{') and '"nodes"' in text_header:
                raise ValueError("Формат JSON пока не поддерживается напрямую.")
        except:
            pass

        # 4. Проверяем текстовый формат INP
        # Ищем типичные секции INP файла
        try:
            text = header.decode('utf-8', errors='ignore')
            if '[TITLE]' in text or '[JUNCTIONS]' in text or '[PIPES]' in text:
                return InpParser(filepath)
        except:
            pass

        # Пробуем другие кодировки
        for enc in ('cp1251', 'latin-1'):
            try:
                text = header.decode(enc)
                if '[TITLE]' in text or '[JUNCTIONS]' in text or '[PIPES]' in text:
                    return InpParser(filepath)
            except:
                continue

        # Если сигнатуры не найдены, доверяем расширению как последнему шансу
        ext = path.suffix.lower()
        if ext == '.net':
            return NetParser(filepath)
        elif ext in ('.inp', '.epanet'):
            return InpParser(filepath)

        raise ValueError(f"Не удалось распознать внутренний формат файла: {path.name}")

    @staticmethod
    def _handle_zip_archive(filepath: str):
        """Если .epanet оказался ZIP-архивом, ищем внутри .inp файл."""
        with zipfile.ZipFile(filepath, 'r') as z:
            inp_files = [f for f in z.namelist() if f.lower().endswith('.inp')]
            if not inp_files:
                raise ValueError(f"Внутри архива {Path(filepath).name} не найден файл .inp")

            # Извлекаем первый найденный .inp файл во временную директорию
            target_file = inp_files[0]
            tmp_dir = tempfile.mkdtemp()
            extracted_path = z.extract(target_file, tmp_dir)

            parser = InpParser(extracted_path)
            # Сохраняем путь к временному файлу, чтобы GUI мог его потом удалить
            parser._temp_file = extracted_path
            return parser