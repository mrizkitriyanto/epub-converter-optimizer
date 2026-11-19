"""The page style of XTC output (and of the preview that simulates it), and the fonts it names.

Every field that reaches Typst source is checked here: a number is a whole number in its range, a
choice is one of its exact strings, a flag is a real boolean, `lang` is a plain language code and
`font` is a family that exists. An error says which field it is and what it takes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "fonts"
TYPST_FAMILY = "Libertinus Serif"  # the one Typst embeds

_WEIGHT_NAMES = {400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}
# family -> weight -> file: the upright static instances. Literata's italic sits next to them and
# Typst picks it from the folder.
BUNDLED_FONTS: dict[str, dict[int, Path]] = {
    "Literata": {w: FONTS_DIR / "literata" / f"Literata-{n}.ttf" for w, n in _WEIGHT_NAMES.items()},
    "Bitter": {w: FONTS_DIR / "bitter" / f"Bitter-{n}.ttf" for w, n in _WEIGHT_NAMES.items()},
    "Lexend Deca": {
        w: FONTS_DIR / "lexend-deca" / f"LexendDeca-{n}.ttf" for w, n in _WEIGHT_NAMES.items()
    },
}

RANGES: dict[str, tuple[int, int]] = {
    "font_size": (16, 64),
    "line_height": (100, 250),  # percent
    "margin": (0, 80),
    "dither_strength": (0, 100),
    "bar_font_size": (8, 32),
    "bar_edge_margin": (0, 40),
    "bar_side_margin": (0, 80),
}
CHOICES: dict[str, tuple] = {
    "align": ("justify", "left"),
    "mode": ("xth", "xtg"),
    "bar_position": ("bottom", "top", "off"),
    "orientation": (0, 90, 180, 270),
}
_LANG = re.compile(r"[a-z]{2,3}")


def _whole(value) -> bool:
    return type(value) is int  # a bool is not a number, and "32" is not 32


@dataclass(frozen=True)
class PageStyle:
    font: str = "Literata"
    font_size: int = 32
    font_weight: int = 400
    line_height: int = 135
    margin: int = 16
    align: str = "justify"
    hyphenate: bool = True
    lang: str = "auto"
    mode: str = "xth"
    dither: bool = True
    dither_strength: int = 80
    negative: bool = False
    bar_position: str = "bottom"
    bar_line: bool = False
    bar_page: bool = True
    bar_book_percent: bool = False
    bar_chapter_page: bool = False
    bar_chapter_percent: bool = False
    bar_chapter_title: bool = True
    bar_chapter_marks: bool = False
    bar_full_width: bool = False
    bar_font_size: int = 14
    bar_edge_margin: int = 4
    bar_side_margin: int = 16
    orientation: int = 0

    def __post_init__(self):
        """Everything but the family and its weights: those depend on the uploaded fonts of the
        job, so `from_json` takes them."""
        for f in fields(self):
            value, name = getattr(self, f.name), f.name
            if name in RANGES:
                low, high = RANGES[name]
                if not (_whole(value) and low <= value <= high):
                    raise ValueError(f"{name} must be a whole number from {low} to {high}")
            elif name in CHOICES:
                if not (type(value) is type(CHOICES[name][0]) and value in CHOICES[name]):
                    raise ValueError(f"{name} must be one of: {', '.join(map(str, CHOICES[name]))}")
            elif name == "lang":
                if not (isinstance(value, str) and (value == "auto" or _LANG.fullmatch(value))):
                    raise ValueError("lang must be auto or a two or three letter language code")
            elif isinstance(f.default, bool) and type(value) is not bool:
                raise ValueError(f"{name} must be true or false")

    @classmethod
    def from_json(cls, d: dict, extra_dirs: Sequence[Path] = ()) -> PageStyle:
        """A style from an object that may hold some of the fields. `extra_dirs` are the folders
        of uploaded fonts, whose families are then known. ValueError for anything that is not
        right."""
        if not isinstance(d, dict):
            raise ValueError("style must be an object")  # noqa: TRY004
        names = {f.name for f in fields(cls)}
        for key in d:
            if key not in names:
                raise ValueError(f"Unknown style field: {key}")
        style = cls(**d)
        weights = available_weights(style.font, extra_dirs) if isinstance(style.font, str) else []
        if not weights:
            raise ValueError("font must be a bundled font, Libertinus Serif or an uploaded font")
        if not (_whole(style.font_weight) and style.font_weight in weights):
            raise ValueError(f"font_weight must be one of: {', '.join(map(str, weights))}")
        return style

    def to_json(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=1)
def _typst_weights() -> list[int]:
    import typst

    found = typst.Fonts(include_system_fonts=False).fonts()
    return sorted({f.weight for f in found if f.family == TYPST_FAMILY and f.style == "normal"})


def _uploaded_weights(family: str, extra_dirs: Sequence[Path]) -> set[int]:
    import typst

    dirs = [str(d) for d in extra_dirs if Path(d).is_dir()]
    if not dirs:
        return set()
    found = typst.Fonts(
        include_system_fonts=False, include_embedded_fonts=False, font_paths=dirs
    ).fonts()
    return {f.weight for f in found if f.family == family and f.style == "normal"}


def available_weights(family: str, extra_dirs: Sequence[Path] = ()) -> list[int]:
    """The weights of a family, from the bundled fonts, Typst's own and the uploaded fonts in
    `extra_dirs`. Empty when no such family exists."""
    weights = set(BUNDLED_FONTS.get(family, ()))
    if family == TYPST_FAMILY:
        weights.update(_typst_weights())
    weights |= _uploaded_weights(family, extra_dirs)
    return sorted(weights)


def font_dirs(extra_dirs: Sequence[Path] = ()) -> list[Path]:
    """The folders Typst reads fonts from: the bundled ones, then the uploads."""
    bundled = sorted({files[400].parent for files in BUNDLED_FONTS.values()})
    return [*bundled, *map(Path, extra_dirs)]
