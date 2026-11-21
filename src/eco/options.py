import os
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

from eco.events import Finding
from eco.style import RANGES, PageStyle

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
FORMATS = ("epub", "xtch", "xtc")
CHAPTER_LIMIT_BYTES = 100_000

_GENERAL_PX = {"small": 1200, "balanced": 1600, "best": 2048}
_GENERAL_QUALITY = {"small": 65, "balanced": 85, "best": 92}
_XTEINK_QUALITY = {"small": 65, "balanced": 80, "best": 92}


@dataclass(frozen=True)
class Options:
    device: str = "x4-pro"
    firmware: str = "any"
    formats: tuple[str, ...] = ("epub",)
    size: str = "balanced"
    mode: str = "auto"
    landscape: bool = False
    ocr: str = "auto"
    title: str | None = None
    author: str | None = None
    lang: str | None = None
    style: PageStyle = field(default_factory=PageStyle)

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


def upgrade_options(options: dict) -> dict:
    """The options of an older job.json in the form of today. M2 wrote `font_size` and no
    `style`: the size becomes the style's, kept within its range. Before the Focus Mode weight a
    style held `focus_strength`: it goes, and the weight takes its default. The browser reads
    these options as they are, so they must hold every field of today."""
    if "font_size" in options:
        options = dict(options)
        low, high = RANGES["font_size"]
        size = min(high, max(low, options.pop("font_size")))
        options.setdefault("style", PageStyle(font_size=size).to_json())
    style = options.get("style")
    if isinstance(style, dict) and ("focus_strength" in style or "focus_weight" not in style):
        style = {key: value for key, value in style.items() if key != "focus_strength"}
        style.setdefault("focus_weight", PageStyle().focus_weight)
        options = {**options, "style": style}
    return options


def options_from_dict(
    options: dict, font_extra_dirs: tuple[Path, ...] = (), findings: list[Finding] | None = None
) -> Options:
    """`Options` from `asdict(Options)` after a trip through JSON."""
    return Options(
        **{
            **options,
            "formats": tuple(options["formats"]),
            "style": PageStyle.from_json(
                options["style"], font_extra_dirs, lenient=True, findings=findings
            ),
        }
    )


@dataclass(frozen=True)
class ImageProfile:
    max_w: int
    max_h: int
    grayscale: bool
    jpeg_quality: int
    png_line_art: bool
    drop_images: bool
    min_px: int
    enhance: bool = False  # photos get more contrast and a light sharpening for e-ink


def image_profile(o: Options) -> ImageProfile:
    screen = DEVICES[o.device]
    if screen is None:
        px = _GENERAL_PX[o.size]
        return ImageProfile(px, px, False, _GENERAL_QUALITY[o.size], False, False, 0)
    drop = o.size == "small" and o.firmware == "stock"
    return ImageProfile(*screen, True, _XTEINK_QUALITY[o.size], True, drop, 20, enhance=True)


def resolve_data_dir(cli_value: str | None) -> Path:
    path = Path(cli_value or os.environ.get("ECO_DATA") or platformdirs.user_data_dir("eco"))
    path = path.expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path
