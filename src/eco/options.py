import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

DEVICES: dict[str, tuple[int, int] | None] = {
    "x4": (480, 800),
    "x4-pro": (480, 800),
    "x4-classic": (480, 800),
    "x3": (528, 792),
    "general": None,
}
FIRMWARES = ("any", "stock", "crosspoint", "crossink")
SIZES = ("small", "balanced", "best")
MODES = ("auto", "reflow", "pages")
OCR_MODES = ("auto", "force", "off")
FORMATS = ("epub",)  # M3 adds "xtch", "xtc"
CHAPTER_LIMIT_BYTES = 100_000

_GENERAL_PX = {"small": 1200, "balanced": 1600, "best": 2048}
_GENERAL_QUALITY = {"small": 65, "balanced": 85, "best": 92}
_XTEINK_QUALITY = {"small": 65, "balanced": 80, "best": 92}


@dataclass(frozen=True)
class Options:
    device: str = "x4"
    firmware: str = "any"
    formats: tuple[str, ...] = ("epub",)
    size: str = "balanced"
    mode: str = "auto"
    landscape: bool = False
    ocr: str = "auto"
    title: str | None = None
    author: str | None = None
    lang: str | None = None
    font_size: int = 32

    def __post_init__(self):
        checks = {
            "device": ([self.device], DEVICES),
            "firmware": ([self.firmware], FIRMWARES),
            "format": (self.formats, FORMATS),
            "size": ([self.size], SIZES),
            "mode": ([self.mode], MODES),
            "ocr": ([self.ocr], OCR_MODES),
        }
        for name, (values, allowed) in checks.items():
            for v in values:
                if v not in allowed:
                    raise ValueError(f"unknown {name}: {v!r}")


@dataclass(frozen=True)
class ImageProfile:
    max_w: int
    max_h: int
    grayscale: bool
    jpeg_quality: int
    png_line_art: bool
    drop_images: bool
    min_px: int


def image_profile(o: Options) -> ImageProfile:
    screen = DEVICES[o.device]
    if screen is None:
        px = _GENERAL_PX[o.size]
        return ImageProfile(px, px, False, _GENERAL_QUALITY[o.size], False, False, 0)
    drop = o.size == "small" and o.firmware == "stock"
    return ImageProfile(*screen, True, _XTEINK_QUALITY[o.size], True, drop, 20)


def resolve_data_dir(cli_value: str | None) -> Path:
    path = Path(cli_value or os.environ.get("ECO_DATA") or platformdirs.user_data_dir("eco"))
    path.mkdir(parents=True, exist_ok=True)
    return path
