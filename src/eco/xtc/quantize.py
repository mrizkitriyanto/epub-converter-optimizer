"""Quantize rendered pages for Xteink screens."""

from io import BytesIO
from itertools import pairwise

import numpy as np
from PIL import Image

from eco.style import PageStyle

XTH_BLACK_MAX = 42
XTH_DARK_MAX = 127
XTH_LIGHT_MAX = 212
XTG_WHITE_MIN = 128


def _nearest(values: np.ndarray, mode: str) -> np.ndarray:
    if mode == "xtg":
        return np.where(values >= XTG_WHITE_MIN, 255, 0).astype(np.uint8)
    return np.select(
        (
            values > XTH_LIGHT_MAX,
            values > XTH_DARK_MAX,
            values > XTH_BLACK_MAX,
        ),
        (255, 170, 85),
        default=0,
    ).astype(np.uint8)


def _fs(region: np.ndarray, levels: np.ndarray, strength: float) -> np.ndarray:
    rows = region.astype(np.float32).tolist()
    level_values = levels.astype(np.float32).tolist()
    midpoints = [(left + right) / 2 for left, right in pairwise(level_values)]
    height, width = region.shape
    for y in range(height):
        for x in range(width):
            old = rows[y][x]
            if old <= midpoints[0]:
                new = level_values[0]
            elif len(midpoints) == 1 or old <= midpoints[1]:
                new = level_values[1]
            elif old <= midpoints[2]:
                new = level_values[2]
            else:
                new = level_values[3]
            rows[y][x] = new
            error = (old - new) * strength
            if x + 1 < width:
                rows[y][x + 1] += error * 7 / 16
            if y + 1 < height:
                if x > 0:
                    rows[y + 1][x - 1] += error * 3 / 16
                rows[y + 1][x] += error * 5 / 16
                if x + 1 < width:
                    rows[y + 1][x + 1] += error / 16
    return np.clip(np.array(rows, dtype=np.float32), 0, 255).astype(np.uint8)


def quantize_page(
    png: bytes, boxes: list[tuple[int, int, int, int]], style: PageStyle
) -> Image.Image:
    """Quantize one rendered page, dithering only the clipped image boxes."""
    with Image.open(BytesIO(png)) as source:
        gray = np.asarray(source.convert("L"))

    result = _nearest(gray, style.mode)
    if style.dither:
        levels = np.array([0, 255] if style.mode == "xtg" else [0, 85, 170, 255], dtype=np.float32)
        height, width = gray.shape
        for left, top, right, bottom in boxes:
            left, top = max(0, left), max(0, top)
            right, bottom = min(width, right), min(height, bottom)
            if left < right and top < bottom:
                result[top:bottom, left:right] = _fs(
                    gray[top:bottom, left:right],
                    levels,
                    style.dither_strength / 100,
                )

    if style.negative:
        result = 255 - result
    return Image.fromarray(result)


# shortcut: the Floyd-Steinberg loop is pure Python over image boxes only; move it to a C or numba
# kernel if image-heavy books get slow.
