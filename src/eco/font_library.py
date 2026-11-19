"""Validated fonts shared by conversions in one data directory."""

import hashlib
import os
import tempfile
from pathlib import Path

import typst

from eco.style import BUNDLED_FONTS, TYPST_FAMILY

MAX_FONT_BYTES = 30 * 1024 * 1024


def faces(path: Path) -> tuple[str, set[tuple[int, str]]]:
    found = typst.Fonts(
        include_system_fonts=False,
        include_embedded_fonts=False,
        font_paths=[str(path.parent)],
    ).fonts()
    matching = [font for font in found if Path(font.path).resolve() == path.resolve()]
    families = {font.family for font in matching}
    if len(families) != 1:
        raise ValueError(f"Not a usable font file: {path.name}")
    family = families.pop()
    if not matching or any(ord(char) < 32 or char in '"\\' for char in family):
        raise ValueError(f"Not a usable font file: {path.name}")
    return family, {(font.weight, font.style) for font in matching}


def list_fonts(data_dir: Path) -> list[dict]:
    folder = data_dir / "fonts"
    families: dict[str, set[tuple[int, str]]] = {}
    if folder.is_dir():
        for path in folder.iterdir():
            if path.suffix.lower() in (".ttf", ".otf"):
                try:
                    family, variants = faces(path)
                except ValueError:
                    continue
                families.setdefault(family, set()).update(variants)
    return [
        {
            "family": name,
            "weights": sorted({weight for weight, _ in variants}),
            "styles": sorted({style for _, style in variants}),
        }
        for name, variants in sorted(families.items())
    ]


def add_font(data_dir: Path, name: str, content: bytes) -> dict:
    suffix = Path(name).suffix.lower()
    if suffix not in (".ttf", ".otf") or not content or len(content) > MAX_FONT_BYTES:
        raise ValueError(f"Not a usable font file: {name}")
    folder = data_dir / "fonts"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    target = folder / f"{digest}{suffix}"
    if target.exists():
        family, variants = faces(target)
        return {
            "family": family,
            "weights": sorted({w for w, _ in variants}),
            "status": "unchanged",
        }
    fd, temporary = tempfile.mkstemp(suffix=suffix, dir=folder)
    staged = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
        family, variants = faces(staged)
        if family in BUNDLED_FONTS or family == TYPST_FAMILY:
            raise ValueError(f"A built-in font already has this name: {family}")
        replaced = False
        for old in folder.iterdir():
            if old == staged or old.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                old_family, old_variants = faces(old)
            except ValueError:
                continue
            if old_family == family and old_variants & variants:
                old.unlink()
                replaced = True
        staged.replace(target)
        return {
            "family": family,
            "weights": sorted({w for w, _ in variants}),
            "status": "replaced" if replaced else "added",
        }
    finally:
        staged.unlink(missing_ok=True)


def remove_font(data_dir: Path, family: str) -> int:
    removed = 0
    folder = data_dir / "fonts"
    if folder.is_dir():
        for path in folder.iterdir():
            if path.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                name, _ = faces(path)
            except ValueError:
                continue
            if name == family:
                path.unlink()
                removed += 1
    return removed
