"""Check body text against the font chosen for XTC rendering."""

import re
import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import typst
from fontTools.ttLib import TTFont
from markdown_it import MarkdownIt

from eco.events import Finding
from eco.style import BUNDLED_FONTS, PageStyle

_MD = MarkdownIt("commonmark", {"html": True}).enable("table")
_PAGE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")


@lru_cache(maxsize=64)
def _cmap(path: Path) -> frozenset[int]:
    with TTFont(path, lazy=True) as font:
        return frozenset(font.getBestCmap() or ())


def _font_file(style: PageStyle, extra_dirs: Sequence[Path]) -> Path | None:
    bundled = BUNDLED_FONTS.get(style.font)
    if bundled:
        return bundled.get(style.font_weight, bundled[400])
    dirs = [str(path) for path in extra_dirs if path.is_dir()]
    if not dirs:
        return None
    fonts = typst.Fonts(include_system_fonts=False, include_embedded_fonts=False, font_paths=dirs)
    for face in fonts.fonts():
        if (
            face.family == style.font
            and face.weight == style.font_weight
            and face.style == "normal"
        ):
            return Path(face.path) if face.path else None
    return None


def missing_characters(
    markdown: str, style: PageStyle, extra_dirs: Sequence[Path] = ()
) -> Finding | None:
    path = _font_file(style, extra_dirs)
    if path is None:
        return None  # Typst's embedded Libertinus has no readable font file.
    covered = _cmap(path)
    text = []
    in_heading = False
    for token in _MD.parse(markdown):
        if token.type == "heading_open":
            in_heading = True
        elif token.type == "heading_close":
            in_heading = False
        elif token.type == "inline" and not in_heading:
            text.extend(
                child.content
                for child in token.children or ()
                if child.type in ("text", "text_special")
            )
    missing = sorted(
        {
            char
            for chunk in text
            for char in chunk
            if unicodedata.category(char)[0] not in "CZ" and ord(char) not in covered
        }
    )
    if not missing:
        return None
    sample = " ".join(missing[:20])
    return Finding(
        0,
        "font_fallback",
        "warning",
        f"{len(missing)} characters missing from {style.font}: {sample}",
    )


def chapter_markdown(markdown: str, *, chapter: int | None, source_page: int | None) -> str:
    """The Markdown section that the live renderer selects for an XTC chapter."""
    lines = markdown.splitlines(keepends=True)
    heads = [
        token.map[0]
        for token in _MD.parse(markdown)
        if token.type == "heading_open" and token.tag == "h1" and token.map
    ]
    if not heads:
        return markdown
    if chapter is not None:
        index = min(max(chapter, 0), len(heads) - 1)
    else:
        marker_lines = [
            n
            for n, line in enumerate(lines)
            if (match := _PAGE.fullmatch(line.strip())) and int(match[1]) <= (source_page or 0)
        ]
        position = marker_lines[-1] if marker_lines else 0
        index = max((n for n, start in enumerate(heads) if start <= position), default=0)
    start = heads[index]
    end = heads[index + 1] if index + 1 < len(heads) else len(lines)
    return "".join(lines[start:end])
