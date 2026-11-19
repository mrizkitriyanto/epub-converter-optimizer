"""Typst page renderer: compiles a book into device-size grayscale pages.

`render_book` turns the Typst source from `md2typst` into one PNG per device page, a map from device
page to source page, and the chapter list. `render_chapter` renders one chapter alone, for the live
preview. `read_map` and `page_file` read a finished cache without reading all of its pages.
"""

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import typst
from PIL import Image

from eco.bookfolder import BookSource
from eco.options import ImageProfile
from eco.render.md2typst import RenderSettings, _str, to_typst

_PPI = 72.0  # 1 pt is 1 px, so a page is exactly the device size
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


@dataclass
class _Compiled:
    rendered: Rendered
    markers: list[tuple[int, int]]  # (source page, 0-based device page), in document order


def render_book(
    src: BookSource,
    *,
    device: str,
    settings: RenderSettings,
    view: str,
    cache_dir: Path | None = None,
    image_profile: ImageProfile | None = None,
) -> Rendered:
    """Render the whole book. With `cache_dir`, whose parent folder must exist, the pages are kept
    there and read from there the next time. Nothing is ever made above `cache_dir`: a cache whose
    folder is deleted meanwhile is FileNotFoundError, not a folder made again."""
    if cache_dir is not None and (cached := _read_cache(cache_dir)) is not None:
        return cached
    files = to_typst(src, device=device, settings=settings, view=view, image_profile=image_profile)
    if cache_dir is None:
        return _compile(files).rendered
    _clear_cache(cache_dir)
    rendered = _compile(files, cache_dir).rendered
    _write_cache(cache_dir, rendered)
    return rendered


def render_chapter(
    src: BookSource,
    *,
    device: str,
    settings: RenderSettings,
    view: str,
    source_page: int | None = None,
    chapter: int | None = None,
    image_profile: ImageProfile | None = None,
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
    images the chapter refers to.
    """
    if (source_page is None) == (chapter is None):
        raise ValueError("Give source_page or chapter, not both and not neither")
    files = to_typst(src, device=device, settings=settings, view=view, image_profile=image_profile)
    main = files["main.typ"].decode()
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
    used = {m[1] for m in _IMAGE_REF.finditer(chunk)}
    excerpt = {"main.typ": f"{head}\n\n{chunk.rstrip()}\n".encode()}
    excerpt |= {key: data for key, data in files.items() if key != "main.typ" and _str(key) in used}
    compiled = _compile(excerpt)
    if chapter is not None:
        return compiled.rendered, 0
    below = [page for src_page, page in compiled.markers if src_page <= source_page]
    return compiled.rendered, below[-1] if below else 0


def _compile(files: dict[str, bytes | Path], folder: Path | None = None) -> _Compiled:
    """Compile `files` in `folder`, or in a temporary folder that is removed afterwards.

    typst-py reads a dict input only for UTF-8 text, so the files go to disk first.
    """
    if folder is not None:
        return _compile_in(files, folder)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        return _compile_in(files, Path(tmp))


def _compile_in(files: dict[str, bytes | Path], folder: Path) -> _Compiled:
    for name, data in files.items():
        target = folder / name
        for below in reversed(Path(name).parents[:-1]):  # never `folder`: it may have been deleted
            (folder / below).mkdir(exist_ok=True)
        if isinstance(data, Path):
            shutil.copyfile(data, target)
        else:
            target.write_bytes(data)
    main, options = folder / "main.typ", {"root": str(folder), "ignore_system_fonts": True}
    raw = typst.compile(main, format="png", ppi=_PPI, **options)
    pngs = raw if isinstance(raw, list) else [raw]  # one page comes back as bare bytes
    marks = _query(main, "<srcpage>", options)
    chapters = [(m["title"], m["page"] - 1) for m in _query(main, "<chap>", options)]
    pages = [_gray(png) for png in pngs]
    markers = [(m["src"], m["page"] - 1) for m in marks]
    page_map, seen = [0] * len(pages), set()
    for src_page, page in markers:
        page_map[page] = src_page  # the last marker on a page wins
        seen.add(page)
    for page in range(1, len(pages)):
        if page not in seen:
            page_map[page] = page_map[page - 1]
    return _Compiled(Rendered(pages, page_map, chapters), markers)


def _query(main: Path, selector: str, options: dict) -> list[dict]:
    return json.loads(typst.query(main, selector, field="value", format="json", **options))


def _gray(png: bytes) -> bytes:
    with Image.open(BytesIO(png)) as im:
        # Typst paints an opaque white page; flatten any transparency onto white all the same.
        if im.mode in ("RGBA", "LA") and im.getchannel("A").getextrema()[0] < 255:
            flat = Image.new("RGBA", im.size, "white")
            flat.alpha_composite(im.convert("RGBA"))
            im = flat
        out = BytesIO()
        im.convert("L").save(out, "PNG")
    return out.getvalue()


# Cache: NNNN.png for each page, then map.json. map.json is written last, so a folder without it
# was never finished and is rendered again.


def page_file(folder: Path, n: int) -> Path:
    """The PNG of page `n` (0-based) of the cache in `folder`."""
    return folder / f"{n + 1:04d}.png"


def read_map(folder: Path) -> tuple[list[int], list[tuple[str, int]]] | None:
    """The page map and the chapters of a finished cache, read without reading any page, or None
    when `folder` holds none: no readable map.json, or a page file that is missing."""
    try:
        data = json.loads((folder / _MAP).read_text(encoding="utf-8"))
        page_map = [int(n) for n in data["page_map"]]
        chapters = [(str(title), int(page)) for title, page in data["chapters"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not page_map or not all(page_file(folder, n).is_file() for n in range(len(page_map))):
        return None
    return page_map, chapters


def _read_cache(folder: Path) -> Rendered | None:
    found = read_map(folder)
    if found is None:
        return None
    page_map, chapters = found
    try:
        pages = [page_file(folder, n).read_bytes() for n in range(len(page_map))]
    except OSError:
        return None
    return Rendered(pages, page_map, chapters)


def _clear_cache(folder: Path) -> None:
    folder.mkdir(exist_ok=True)  # not its parents: a cache inside a deleted folder is not made
    (folder / _MAP).unlink(missing_ok=True)
    for path in folder.iterdir():
        if _PAGE_FILE.fullmatch(path.name):
            path.unlink()


def _write_cache(folder: Path, rendered: Rendered) -> None:
    for n, png in enumerate(rendered.pages):
        page_file(folder, n).write_bytes(png)
    data = {"page_map": rendered.page_map, "chapters": rendered.chapters}
    tmp = folder / f"{_MAP}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(folder / _MAP)
