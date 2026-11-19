"""Typst page renderer: compiles a book into device-size grayscale pages.

`render_book` turns the Typst source from `md2typst` into one PNG per device page, a map from device
page to source page, the chapter list and the box of every image on each page. `render_chapter`
renders one chapter alone, for the live preview. `read_map` and `page_file` read a finished cache
without reading all of its pages.

A page is laid out the way the style's orientation says (on its side for 90 and 270) and turned
back, so a PNG is always the device's own size and its boxes are in the pixels of that PNG.
"""

import json
import math
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import typst
from PIL import Image

from eco.bookfolder import BookSource
from eco.options import ImageProfile
from eco.render.md2typst import _str, _to_typst, to_typst
from eco.style import PageStyle, font_dirs

_PPI = 72.0  # 1 pt is 1 px, so a page is exactly the device size
# How PIL turns a page clockwise by the style's orientation (its names count the other way).
_TURN = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}
Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in px, from the top left corner of a page
_NOISE = 1e-3  # px
_MAP = "map.json"
_PAGE_FILE = re.compile(r"\d{4}\.png")
# `to_typst` starts every chapter with these two lines (break, then its marker).
_CHAPTER_START = re.compile(r"(?m)^(?=#pagebreak\(weak: true\)\n#context \[#metadata\(\(title: )")
_SOURCE_MARKER = re.compile(r"(?m)^[ \t]*#context \[#metadata\(\(src: (\d+), page:")
_IMAGE_REF = re.compile(r'image\("((?:[^"\\]|\\.)*)"')


class ChapterNotFound(LookupError):
    """`render_chapter` was asked for a chapter that the book does not have."""


@dataclass
class Rendered:
    pages: list[bytes]  # PNG, 8-bit grayscale, exactly the device size
    page_map: list[int]  # source page shown on device page i (1-based, 0 = unknown)
    chapters: list[tuple[str, int]]  # (title, first device page, 0-based)
    image_boxes: list[list[Box]]  # the boxes of the images on device page i, as the PNG shows it


@dataclass
class _Compiled:
    rendered: Rendered
    markers: list[tuple[int, int]]  # (source page, 0-based device page), in document order


def render_book(
    src: BookSource,
    *,
    device: str,
    style: PageStyle,
    view: str,
    cache_dir: Path | None = None,
    image_profile: ImageProfile | None = None,
    font_extra_dirs: Sequence[Path] = (),
) -> Rendered:
    """Render the whole book. `font_extra_dirs` are the folders of uploaded fonts, which the style
    may name. With `cache_dir`, whose parent folder must exist, the pages are kept there and read
    from there the next time (the caller keeps one folder for each style). Nothing is ever made
    above `cache_dir`: a cache whose folder is deleted meanwhile is FileNotFoundError, not a
    folder made again."""
    if cache_dir is not None and (cached := _read_cache(cache_dir)) is not None:
        return cached
    files = to_typst(src, device=device, style=style, view=view, image_profile=image_profile)
    if cache_dir is None:
        return _compile(files, style, font_extra_dirs).rendered
    _clear_cache(cache_dir)
    rendered = _compile(files, style, font_extra_dirs, cache_dir).rendered
    _write_cache(cache_dir, rendered)
    return rendered


def render_chapter(
    src: BookSource,
    *,
    device: str,
    style: PageStyle,
    view: str,
    source_page: int | None = None,
    chapter: int | None = None,
    image_profile: ImageProfile | None = None,
    font_extra_dirs: Sequence[Path] = (),
) -> tuple[Rendered, int]:
    """Render one chapter: the one that holds `source_page`, or the one at index `chapter`.

    With `source_page` the chapter is the one that holds the last page marker at or below it (the
    first chapter when there is none), and the answer is the excerpt and the index of the excerpt
    page that holds the marker of `source_page`. With `chapter` (0-based, in the order of
    `Rendered.chapters`) the index is 0, the chapter's first page, and ChapterNotFound says that
    the book has no such chapter. A book with no chapter heading is one chapter, index 0, though
    its `chapters` list is empty; the text before the first heading is no chapter. Give one of the
    two, not both.

    Each chapter starts on a new page, so the pages of the source text cut at the chapter start are
    laid out exactly as inside the whole book. The excerpt keeps the book's own preamble and the
    images the chapter refers to. What the progress bar counts from the start of the book (the
    page and its share of the book) is counted from the start of the excerpt.
    """
    if (source_page is None) == (chapter is None):
        raise ValueError("Give source_page or chapter, not both and not neither")
    mapped = _to_typst(
        src,
        device,
        style,
        view,
        image_profile,
        defer_images=True,
    )
    main = mapped["main.typ"].decode()
    head, chunk = _chapter(main, source_page, chapter)
    used = {m[1] for m in _IMAGE_REF.finditer(chunk)}
    selected = {
        path.resolve()
        for key, path in mapped.items()
        if key != "main.typ" and isinstance(path, Path) and _str(key) in used
    }
    files = _to_typst(
        src,
        device,
        style,
        view,
        image_profile,
        selected_images=selected,
    )
    main = files["main.typ"].decode()
    head, chunk = _chapter(main, source_page, chapter)
    used = {m[1] for m in _IMAGE_REF.finditer(chunk)}
    excerpt = {"main.typ": f"{head}\n\n{chunk.rstrip()}\n".encode()}
    excerpt |= {key: data for key, data in files.items() if key != "main.typ" and _str(key) in used}
    compiled = _compile(excerpt, style, font_extra_dirs)
    if chapter is not None:
        return compiled.rendered, 0
    below = [page for src_page, page in compiled.markers if src_page <= source_page]
    return compiled.rendered, below[-1] if below else 0


def _chapter(main: str, source_page: int | None, chapter: int | None) -> tuple[str, str]:
    head, _, body = main.partition("\n\n")  # the preamble has no blank line
    chunks = _CHAPTER_START.split(body)  # what comes before the first chapter, then each chapter
    if chapter is not None:
        chapters = chunks[1:] or chunks  # with no heading the whole body is the one chapter
        if not 0 <= chapter < len(chapters):
            raise ChapterNotFound(f"No chapter {chapter}")
        chunk = chapters[chapter]
    else:
        chosen = next((n for n, chunk in enumerate(chunks) if chunk.strip()), 0)
        for n, chunk in enumerate(chunks):
            if any(int(m[1]) <= source_page for m in _SOURCE_MARKER.finditer(chunk)):
                chosen = n
        chunk = chunks[chosen]
    return head, chunk


def _compile(
    files: dict[str, bytes | Path],
    style: PageStyle,
    font_extra_dirs: Sequence[Path],
    folder: Path | None = None,
) -> _Compiled:
    """Compile `files` in `folder`, or in a temporary folder that is removed afterwards.

    typst-py reads a dict input only for UTF-8 text, so the files go to disk first.
    """
    if folder is not None:
        return _compile_in(files, style, font_extra_dirs, folder)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        return _compile_in(files, style, font_extra_dirs, Path(tmp))


def _compile_in(
    files: dict[str, bytes | Path], style: PageStyle, font_extra_dirs: Sequence[Path], folder: Path
) -> _Compiled:
    for name, data in files.items():
        target = folder / name
        for below in reversed(Path(name).parents[:-1]):  # never `folder`: it may have been deleted
            (folder / below).mkdir(exist_ok=True)
        if isinstance(data, Path):
            shutil.copyfile(data, target)
        else:
            target.write_bytes(data)
    main = folder / "main.typ"
    options = {
        "root": str(folder),
        "ignore_system_fonts": True,
        "font_paths": [str(d) for d in font_dirs(font_extra_dirs)],
    }
    raw = typst.compile(main, format="png", ppi=_PPI, **options)
    pngs = raw if isinstance(raw, list) else [raw]  # one page comes back as bare bytes
    marks = _query(main, "<srcpage>", options)
    chapters = [(m["title"], m["page"] - 1) for m in _query(main, "<chap>", options)]
    with Image.open(BytesIO(pngs[0])) as first:
        laid_out = first.size  # before the pages are turned
    boxes = _image_boxes(_query(main, "<imgbox>", options), len(pngs), laid_out, style.orientation)
    pages = [_gray(png, style.orientation) for png in pngs]
    markers = [(m["src"], m["page"] - 1) for m in marks]
    page_map, seen = [0] * len(pages), set()
    for src_page, page in markers:
        page_map[page] = src_page  # the last marker on a page wins
        seen.add(page)
    for page in range(1, len(pages)):
        if page not in seen:
            page_map[page] = page_map[page - 1]
    return _Compiled(Rendered(pages, page_map, chapters, boxes), markers)


def _query(main: Path, selector: str, options: dict) -> list[dict]:
    return json.loads(typst.query(main, selector, field="value", format="json", **options))


def _gray(png: bytes, orientation: int) -> bytes:
    """The page as 8-bit grayscale, turned clockwise by `orientation` degrees."""
    with Image.open(BytesIO(png)) as im:
        # Typst paints an opaque white page; flatten any transparency onto white all the same.
        if im.mode in ("RGBA", "LA") and im.getchannel("A").getextrema()[0] < 255:
            flat = Image.new("RGBA", im.size, "white")
            flat.alpha_composite(im.convert("RGBA"))
            im = flat
        page = im.convert("L")
        if orientation:
            page = page.transpose(_TURN[orientation])
        out = BytesIO()
        page.save(out, "PNG")
    return out.getvalue()


def _image_boxes(
    marks: list[dict], pages: int, size: tuple[int, int], orientation: int
) -> list[list[Box]]:
    """The boxes of the images on each page, from the `<imgbox>` markers of pages that were laid
    out `size` px wide and tall. A box takes every pixel that its image touches, inside the page,
    and is turned with the page."""
    width, height = size
    boxes: list[list[Box]] = [[] for _ in range(pages)]
    for m in marks:
        # A layout's lengths carry float noise: 40.0000001 must not make the box one px wider.
        x0, y0 = max(0, math.floor(m["x"] + _NOISE)), max(0, math.floor(m["y"] + _NOISE))
        x1 = min(width, math.ceil(m["x"] + m["w"] - _NOISE))
        y1 = min(height, math.ceil(m["y"] + m["h"] - _NOISE))
        if x0 < x1 and y0 < y1 and 1 <= m["page"] <= pages:
            box = (x0, y0, x1, y1)
            boxes[m["page"] - 1].append(_turn_box(box, orientation, width, height))
    return boxes


def _turn_box(box: Box, orientation: int, width: int, height: int) -> Box:
    """`box` of a page `width` by `height` px, as it lies when the page is turned clockwise by
    `orientation` degrees."""
    x0, y0, x1, y1 = box
    if orientation == 90:
        return height - y1, x0, height - y0, x1
    if orientation == 180:
        return width - x1, height - y1, width - x0, height - y0
    if orientation == 270:
        return y0, width - x1, y1, width - x0
    return box


# Cache: NNNN.png for each page, then map.json. map.json is written last, so a folder without it
# was never finished and is rendered again.


def page_file(folder: Path, n: int) -> Path:
    """The PNG of page `n` (0-based) of the cache in `folder`."""
    return folder / f"{n + 1:04d}.png"


def _read(folder: Path) -> tuple[list[int], list[tuple[str, int]], list[list[Box]]] | None:
    """The page map, the chapters and the image boxes of a finished cache, read without reading
    any page, or None when `folder` holds none: no readable map.json (one without the boxes is
    from before they were kept), or a page file that is missing."""
    try:
        data = json.loads((folder / _MAP).read_text(encoding="utf-8"))
        page_map = [int(n) for n in data["page_map"]]
        chapters = [(str(title), int(page)) for title, page in data["chapters"]]
        boxes = [
            [(int(a), int(b), int(c), int(d)) for a, b, c, d in page] for page in data["boxes"]
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not page_map or len(boxes) != len(page_map):
        return None
    if not all(page_file(folder, n).is_file() for n in range(len(page_map))):
        return None
    return page_map, chapters, boxes


def read_map(folder: Path) -> tuple[list[int], list[tuple[str, int]]] | None:
    """The page map and the chapters of a finished cache, read without reading any page, or None
    when `folder` holds none."""
    found = _read(folder)
    return None if found is None else found[:2]


def _read_cache(folder: Path) -> Rendered | None:
    found = _read(folder)
    if found is None:
        return None
    page_map, chapters, boxes = found
    try:
        pages = [page_file(folder, n).read_bytes() for n in range(len(page_map))]
    except OSError:
        return None
    return Rendered(pages, page_map, chapters, boxes)


def _clear_cache(folder: Path) -> None:
    folder.mkdir(exist_ok=True)  # not its parents: a cache inside a deleted folder is not made
    (folder / _MAP).unlink(missing_ok=True)
    for path in folder.iterdir():
        if _PAGE_FILE.fullmatch(path.name):
            path.unlink()


def _write_cache(folder: Path, rendered: Rendered) -> None:
    for n, png in enumerate(rendered.pages):
        page_file(folder, n).write_bytes(png)
    data = {
        "page_map": rendered.page_map,
        "chapters": rendered.chapters,
        "boxes": rendered.image_boxes,
    }
    tmp = folder / f"{_MAP}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(folder / _MAP)
