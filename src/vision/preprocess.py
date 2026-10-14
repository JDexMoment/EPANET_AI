"""Работа с изображениями для трека «скриншоты → ответ» (VLM).

Здесь только то, что нужно до модели:
  • метрики картинки (размер, вес);
  • dHash — быстрый «отпечаток» для поиска почти одинаковых скриншотов
    (без него train и test «протекут» друг в друга: скриншоты одной сессии похожи);
  • приведение к безопасному размеру (Qwen3-VL обучен на ~1M пикселей:
    больше — только вред и лишние токены);
  • эвристика «где на экране мелкий текст» — чтобы при желании подать модели
    дополнительный увеличенный фрагмент (таблица/панель данных читается лучше).

Зависимости: Pillow. OCR здесь НЕ вызывается — он в src/vision/detect_screen.py.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


# ─────────────────────────────── базовое

def is_image(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def open_image(path: Path | str) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)          # чтобы повёрнутые снимки не ломали разметку
    return img.convert("RGB")


def image_info(path: Path | str) -> dict:
    p = Path(path)
    with Image.open(p) as im:
        w, h = im.size
        mode = im.mode
    return {"width": w, "height": h, "aspect": round(w / h, 3) if h else 0.0,
            "bytes": p.stat().st_size, "mode": mode}


# ─────────────────────────────── почти одинаковые картинки

def dhash(path: Path | str, hash_size: int = 8) -> str:
    """dHash: 64 бита в 16 hex-символах. Инвариантен к масштабу и мелкому шуму."""
    with open_image(path) as img:
        small = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(hash_size):
        base = row * (hash_size + 1)
        for col in range(hash_size):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return f"{bits:0{hash_size * hash_size // 4}x}"


def hamming(a: str, b: str) -> int:
    """Расстояние Хэмминга между двумя dHash-строками (в битах)."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


# ─────────────────────────────── приведение к рабочему размеру

def shrink_to_limit(img: Image.Image, max_pixels: int, max_side: int, min_side: int = 0) -> Image.Image:
    """Уменьшает картинку до лимита по площади и по длинной стороне."""
    w, h = img.size
    scale = min(1.0, (max_pixels / (w * h)) ** 0.5 if w * h > 0 else 1.0, max_side / max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    if min_side and min(img.size) < min_side:
        k = min_side / min(img.size)
        img = img.resize((int(img.width * k), int(img.height * k)), Image.Resampling.LANCZOS)
    return img


def prepare_image(src: Path | str, dst: Path | str, max_pixels: int = 1280000,
                  max_side: int = 1600, min_side: int = 640) -> dict:
    """Готовит рабочую копию скриншота. Оригинал не трогает."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = shrink_to_limit(open_image(src), max_pixels, max_side, min_side)
    img.save(dst, format="PNG", optimize=True)
    return {"dst": str(dst), "width": img.width, "height": img.height,
            "bytes": dst.stat().st_size}


# ─────────────────────────────── где мелкий текст (эвристика)

def guess_text_regions(path: Path | str, top_k: int = 2, min_gap: int = 12) -> list[tuple[int, int, int, int]]:
    """Возвращает до top_k прямоугольников, где, скорее всего, таблицы с числами.

    Эвристика без обучения: считаем «краевые» пиксели (резкие перепады яркости —
    это символы и линии таблиц), строим профиль по строкам, берём самые плотные
    полосы. Нужна для опции «дополнительно подать увеличенный фрагмент».
    """
    img = open_image(path).convert("L")
    w, h = img.size
    edges = img.filter(ImageFilter.FIND_EDGES)
    if max(w, h) > 2000:                      # экономим время на больших скриншотах
        edges = edges.resize((w // 2, h // 2), Image.Resampling.BILINEAR)
    px = edges.load()
    ew, eh = edges.size
    rows = []
    for y in range(0, eh):
        s = 0
        for x in range(0, ew, 2):
            s += px[x, y]
        rows.append(s / (ew / 2 + 1))

    thr = max(12.0, sum(rows) / len(rows) * 1.4)
    bands: list[list[int]] = []
    start = None
    for y, v in enumerate(rows):
        if v >= thr and start is None:
            start = y
        elif v < thr and start is not None:
            if y - start >= min_gap:
                bands.append([start, y])
            start = None
    if start is not None and eh - start >= min_gap:
        bands.append([start, eh])
    bands.sort(key=lambda b: b[1] - b[0], reverse=True)

    k = eh / h if h else 1.0
    out: list[tuple[int, int, int, int]] = []
    for y0, y1 in bands[:top_k]:
        pad = 8
        out.append((0, max(0, int(y0 / k) - pad), w, min(h, int(y1 / k) + pad)))
    return out


def crop_and_upscale(path: Path | str, box: tuple[int, int, int, int], factor: float = 2.0) -> Image.Image:
    img = open_image(path).crop(box)
    if factor != 1.0:
        img = img.resize((int(img.width * factor), int(img.height * factor)), Image.Resampling.LANCZOS)
    return img
