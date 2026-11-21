"""The previews of the review stage: the original PDF page, the device pages, and the live preview.

All the caches of file `n` of a job are under `<job>/preview/<n>/`, so two files of one job never
share one, and they go when the job does:

    source/<page>.png         a PDF page as the PDF draws it
    book/                     the book the pages are rendered from, when no folder holds it already:
                              an EPUB read by `epub_to_book`, or the page images of a PDF that was
                              converted with `mode=pages` (its worker built them in a folder that is
                              gone). A reflow PDF uses the book folder of its extraction.
    <format>-<view>-<style>/  the device pages of the whole book: `render_book`'s cache. The
                              style is a short hash of the page style the pages were rendered
                              with, so that no two styles share a folder.

The device pages are rendered with the job's own device, size preset (as the image profile) and
page style. The live preview renders one chapter with the job's page style, but the font size and
size preset it is given. An EPUB's preview takes the style as a simulation, without its
orientation: an EPUB has none, the reader turns its pages. The live preview writes nothing to the
disk and keeps its last answers, only the PNG and where it sits in the excerpt, in memory.

The routes run on a pool of threads. Renders and book builds are done one at a time for a folder:
the render cache rewrites its map and compiles inside its folder, and on Windows a file that
another thread holds cannot be removed. PDFium is used by one thread at a time in the whole
process: it is not thread-safe, not even for two documents (see pypdfium2's documentation). The
reading of an uploaded PDF for the file rows on Select (`describe_pdf`) takes the same lock.

Every number of a page is 1-based, as the page shows it: the page of a PDF, the device page, and
what `page_map` and `chapters` hold. A chapter is counted from 0, in the order of `chapters`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import weakref
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

from pypdfium2 import PdfiumError

from eco.bookfolder import BookSource, load_source
from eco.epub.optimizer import DRMError
from eco.epub.reader import epub_to_book
from eco.font_coverage import chapter_markdown, missing_characters
from eco.options import SIZES, Options, image_profile, options_from_dict
from eco.pdf.pages import PdfOpenError, inspect_pdf, page_count, render_page_fit
from eco.pipeline import page_book
from eco.render.pages import ChapterNotFound, page_file, read_map, render_book, render_chapter
from eco.style import PageStyle
from eco.web.jobs import JobFile, JobInfo, JobStore
from eco.web.strings import STRINGS
from eco.xtc.codec import decode_page
from eco.xtc.container import read_container
from eco.xtc.quantize import quantize_page

FORMATS = ("epub", "xtch", "xtc")
VIEWS = ("crosspoint", "crossink", "stock")
SOURCE_WIDTH = 600  # px
SOURCE_MAX_HEIGHT = 10 * SOURCE_WIDTH  # a page that is taller is drawn smaller
LIVE_ANSWERS = 32
BOOK = "book.md"
# Seconds of conversion per page. Select multiplies them by a PDF's pages for the estimate in
# its row. Provisional. `digital` and `scanned` come from the PDF engine spike on the owner's M3 Mac
# (docs/research/2026-11-16-spike-pdf-engines.md, row "Waktu per 13 halaman": Docling took 8-10 s for
# 13 digital pages and 27 s for 13 scanned ones, so 0.7 and 2.1 s a page). `pages`, for a PDF made
# into page images, has not been measured. The acceptance run recalibrates all three.
SECONDS_PER_PAGE = {"digital": 0.7, "scanned": 2.1, "pages": 0.2}

_PDFIUM = threading.Lock()


class PreviewError(Exception):
    """An answer that is no picture and no text: the HTTP status, and the message of its `error`."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class _NoBook(Exception):
    """The file has no book to preview or to show as text."""


class Live(NamedTuple):
    png: bytes  # the page of the excerpt that is shown
    index: int  # where it is in the excerpt, from 0
    pages: int  # how many pages the excerpt has
    font_fallback: str | None = None


class _Answers:
    """The last `size` answers of the live preview, the least recently used one out first."""

    def __init__(self, size: int):
        self._size = size
        self._items: OrderedDict[tuple, Live] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Live | None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        return None

    def put(self, key: tuple, answer: Live) -> None:
        with self._lock:
            self._items[key] = answer
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)


def _font_dirs(store: JobStore, info: JobInfo) -> tuple[Path, ...]:
    folder = store.root / info.id / "fonts"
    library = store.root.parent / "fonts"
    return tuple(path for path in (library, folder) if path.is_dir())


def _job_options(store: JobStore, info: JobInfo) -> Options:
    return options_from_dict(info.options, _font_dirs(store, info))


def _shown(style: PageStyle, fmt: str) -> PageStyle:
    """The style a preview is rendered with: an EPUB's has no orientation."""
    return replace(style, orientation=0) if fmt == "epub" else style


def _style_key(style: PageStyle) -> str:
    """A short name for a style, the same for equal styles and different for any two others."""
    data = json.dumps(style.to_json(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()[:12]


def _check_choice(fmt: str, view: str) -> None:
    if fmt not in FORMATS:
        raise PreviewError(400, STRINGS["error_format"].format(format=fmt))
    if view not in VIEWS:
        raise PreviewError(400, STRINGS["error_view"].format(view=view))


def _check_converted(file: JobFile, fmt: str | None = None) -> None:
    """409 until the file has an output: in `fmt` when one is given, in any format otherwise."""
    if not (fmt in file.outputs if fmt else file.outputs):
        raise PreviewError(409, STRINGS["error_not_converted"])


def _pdf_pages(file: JobFile) -> int:
    try:
        with _PDFIUM:
            return page_count(Path(file.path))
    except PdfOpenError:
        raise PreviewError(422, STRINGS["error_pdf"]) from None


def _draw(file: JobFile, page: int) -> bytes:
    """The PNG of a PDF page. 404 for a page the PDF does not have."""
    try:
        with _PDFIUM:
            if not 1 <= page <= page_count(Path(file.path)):
                raise PreviewError(404, STRINGS["error_page"])
            image = render_page_fit(Path(file.path), page, SOURCE_WIDTH, SOURCE_MAX_HEIGHT)
    except PdfOpenError:
        raise PreviewError(422, STRINGS["error_pdf"]) from None
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def describe_pdf(path: Path) -> dict:
    """What a file row on Select shows of a PDF before it is converted: its pages, how many of
    them are scanned (M1's rule, the one the `read` stage counts by) and the rates that turn them
    into an estimate. 400, with M1's own message, for a PDF that cannot be opened, and 400 for
    one that opens but has a page that PDFium cannot read."""
    try:
        with _PDFIUM:
            infos = inspect_pdf(path)
    except PdfOpenError as error:
        raise PreviewError(400, str(error)) from None
    except PdfiumError:
        raise PreviewError(400, STRINGS["error_pdf"]) from None
    return {
        "pages": len(infos),
        "scanned_pages": sum(info.is_scanned for info in infos),
        "scanned": [info.number for info in infos if info.is_scanned],
        "blank": [info.number for info in infos if info.is_blank],
        "seconds_per_page": dict(SECONDS_PER_PAGE),
    }


class Previews:
    """The previews of the files of the jobs in `store`. One of these serves all the requests."""

    def __init__(self, store: JobStore):
        self._store = store
        self._answers = _Answers(LIVE_ANSWERS)
        self._guard = threading.Lock()  # for `_locks`
        # A lock goes when no thread uses it any more, so the folders of old jobs leave nothing.
        self._locks: weakref.WeakValueDictionary[Path, threading.Lock] = (
            weakref.WeakValueDictionary()
        )

    # Source pages

    def source_page(self, info: JobInfo, n: int, page: int) -> bytes:
        """The PDF page as a PNG, 600 px wide (less for a page that would be over 6,000 px tall).
        It needs only the upload, so it works before the conversion. 404 for a page the PDF does
        not have and for a file that is not a PDF."""
        file = info.files[n]
        if file.kind != "pdf":
            raise PreviewError(404, STRINGS["error_no_source"])
        with self._job_kept(info):
            folder = self._folder(info, n, "source")
            target = folder / f"{page}.png"
            if target.is_file():  # written whole, by a rename: never half a file
                return target.read_bytes()
            with self._hold(folder):
                if not target.is_file():
                    png = _draw(file, page)
                    partial = target.with_name(f"{target.name}.tmp")
                    partial.write_bytes(png)
                    os.replace(partial, target)
                return target.read_bytes()

    # Device pages of the whole book

    def pages(self, info: JobInfo, n: int, fmt: str, view: str) -> dict:
        """What the page needs to show the device pages next to the PDF pages."""
        _check_choice(fmt, view)
        file = info.files[n]
        _check_converted(file, fmt)
        with self._job_kept(info):
            _, page_map, chapters = self._cache(info, n, fmt, view)
            source_pages = _pdf_pages(file) if file.kind == "pdf" else 0
        return {
            "source_pages": source_pages,
            "device_pages": len(page_map),
            "page_map": page_map,
            "chapters": [[title, page + 1] for title, page in chapters],
        }

    def device_page(self, info: JobInfo, n: int, fmt: str, view: str, page: int) -> bytes:
        """The PNG of one device page. Only that page is read from the cache."""
        _check_choice(fmt, view)
        _check_converted(info.files[n], fmt)
        if fmt != "epub":
            return self.xtc_page(info, n, page, fmt)
        with self._job_kept(info):
            folder, page_map, _ = self._cache(info, n, fmt, view)
            if not 1 <= page <= len(page_map):
                raise PreviewError(404, STRINGS["error_page"])
            return page_file(folder, page - 1).read_bytes()

    def xtc_page_count(self, info: JobInfo, n: int, fmt: str) -> int:
        """The pages of the XTC/XTCH file, from its header: nothing is rendered."""
        file = info.files[n]
        if fmt not in ("xtch", "xtc"):
            raise PreviewError(404, STRINGS["error_output"])
        _check_converted(file, fmt)
        with self._job_kept(info):
            _, pages, _ = read_container(Path(file.outputs[fmt]).read_bytes())
        return len(pages)

    def xtc_page(self, info: JobInfo, n: int, page: int, fmt: str | None = None) -> bytes:
        """A page decoded from the XTC/XTCH file produced by the conversion."""
        file = info.files[n]
        fmt = fmt or ("xtch" if "xtch" in file.outputs else "xtc")
        if fmt not in ("xtch", "xtc"):
            raise PreviewError(404, STRINGS["error_output"])
        _check_converted(file, fmt)
        with self._job_kept(info):
            folder = self._folder(info, n, f"decoded-{fmt}")
            target = page_file(folder, page - 1)
            if target.is_file():
                return target.read_bytes()
            with self._hold(folder):
                if not target.is_file():
                    _, pages, _ = read_container(Path(file.outputs[fmt]).read_bytes())
                    if not 1 <= page <= len(pages):
                        raise PreviewError(404, STRINGS["error_page"])
                    out = BytesIO()
                    decode_page(pages[page - 1]).save(out, "PNG")
                    partial = target.with_name(f"{target.name}.tmp")
                    partial.write_bytes(out.getvalue())
                    os.replace(partial, target)
                return target.read_bytes()

    def _cache(
        self, info: JobInfo, n: int, fmt: str, view: str
    ) -> tuple[Path, list[int], list[tuple[str, int]]]:
        """The folder of the device pages, rendered now when it holds none, and its page map and
        chapters (the chapters' pages from 0)."""
        options = _job_options(self._store, info)
        style = _shown(options.style, fmt)
        folder = self._folder(info, n, f"{fmt}-{view}-{_style_key(style)}")
        with self._hold(folder):
            found = read_map(folder)
            if found is None:
                render_book(
                    self._source(info, n),
                    device=options.device,
                    style=style,
                    view="xtc" if fmt != "epub" else view,
                    cache_dir=folder,
                    image_profile=None if fmt != "epub" else image_profile(options),
                    font_extra_dirs=_font_dirs(self._store, info),
                )
                found = read_map(folder)
        if found is None:
            raise PreviewError(404, STRINGS["error_no_preview"])
        return (folder, *found)

    # Live preview

    def live(
        self,
        info: JobInfo,
        n: int,
        fmt: str,
        view: str,
        *,
        font_size: int | None,
        size: str | None,
        page: int | None,
        chapter: int | None,
        style: PageStyle | None = None,
    ) -> Live:
        """One page of a chapter rendered now with `font_size` and the `size` preset (the job's own
        when None). The chapter is the one that holds source page `page` of a PDF, or number
        `chapter` of the book. Answers are kept by every one of their parameters."""
        _check_choice(fmt, view)
        options = _job_options(self._store, info)
        style = style or options.style
        font_size = style.font_size if font_size is None else font_size
        style = replace(style, font_size=font_size)
        size = options.size if size is None else size
        if size not in SIZES:
            raise PreviewError(400, STRINGS["error_size"].format(size=size))
        file = info.files[n]
        _check_converted(file)
        if page is not None and file.kind != "pdf":
            raise PreviewError(404, STRINGS["error_no_source"])
        key = (info.id, n, fmt, view, _style_key(style), size, page, chapter)
        if (answer := self._answers.get(key)) is not None:
            return answer
        with self._job_kept(info):
            if page is not None and not 1 <= page <= _pdf_pages(file):
                raise PreviewError(404, STRINGS["error_page"])
            try:
                source = self._source(info, n)
                excerpt, index = render_chapter(
                    source,
                    device=options.device,
                    style=_shown(style, fmt),
                    view="xtc" if fmt != "epub" else view,
                    source_page=page,
                    chapter=chapter,
                    image_profile=(
                        image_profile(replace(options, size=size)) if fmt == "epub" else None
                    ),
                    font_extra_dirs=_font_dirs(self._store, info),
                )
            except ChapterNotFound:
                raise PreviewError(404, STRINGS["error_chapter"]) from None
        png = excerpt.pages[index]
        if fmt != "epub":
            image = quantize_page(
                png,
                excerpt.image_boxes[index],
                replace(style, mode="xth" if fmt == "xtch" else "xtg"),
            )
            out = BytesIO()
            image.save(out, "PNG")
            png = out.getvalue()
        fallback = None
        if fmt != "epub":
            section = chapter_markdown(source.markdown, chapter=chapter, source_page=page)
            if finding := missing_characters(section, style, _font_dirs(self._store, info)):
                fallback = finding.message
        answer = Live(png, index, len(excerpt.pages), fallback)  # not the whole excerpt
        self._answers.put(key, answer)
        return answer

    # Text

    def text(self, info: JobInfo, n: int) -> Path:
        """The file that holds the book's Markdown: the upload of a Markdown file, the `book.md` that
        an EPUB was read into, or the `book.md` of a reflow PDF. A PDF with no book folder (it was
        converted with `mode=pages`) has none: its book is only pictures."""
        file = info.files[n]
        _check_converted(file)
        if file.kind == "pdf" and not file.book_dir:
            raise PreviewError(404, STRINGS["error_no_text"])
        with self._job_kept(info):
            try:
                book = self._book(info, n)
            except _NoBook:
                raise PreviewError(404, STRINGS["error_no_text"]) from None
        return book if book.is_file() else book / BOOK

    # The book

    def _source(self, info: JobInfo, n: int) -> BookSource:
        try:
            return load_source(self._book(info, n))
        except _NoBook:
            raise PreviewError(404, STRINGS["error_no_preview"]) from None

    def _book(self, info: JobInfo, n: int) -> Path:
        """The book of file `n`: the Markdown file itself, or a folder that holds a `book.md`."""
        file = info.files[n]
        if file.kind == "md":
            if not Path(file.path).is_file():
                raise _NoBook
            return Path(file.path)
        if file.book_dir:  # a PDF that was converted by reflow: its extraction is in the cache
            book = Path(file.book_dir)
            if not (book / BOOK).is_file():
                raise _NoBook
            return book
        options = _job_options(self._store, info)
        if file.kind == "pdf" and options.mode != "pages":
            raise _NoBook
        folder = self._folder(info, n, "book")
        with self._hold(folder):
            if not (folder / "report.json").is_file():  # written last: a folder without it is
                self._build_in_place(file, options, folder)  # what a build that failed left
        return folder

    def _build_in_place(self, file: JobFile, options: Options, folder: Path) -> None:
        """Build the book of `file` and put it in `folder`, in place of what is there.

        M1's builders make the folders they write into with all their parents, so a job deleted
        during a build would be made again. They build in a folder of their own in the jobs
        folder (one without a job.json, so a server killed meanwhile leaves what the next start
        purges), and the book is moved into the job by a rename, which fails if the job is gone."""
        built = self._store.reserve()
        try:
            try:
                self._build(file, options, built / "book")
            except (DRMError, ValueError, PdfOpenError):
                raise _NoBook from None
            shutil.rmtree(folder, ignore_errors=True)
            os.replace(built / "book", folder)
        finally:
            shutil.rmtree(built, ignore_errors=True)

    @staticmethod
    def _build(file: JobFile, options: Options, folder: Path) -> None:
        if file.kind == "epub":
            epub_to_book(Path(file.path), folder)
        else:  # a PDF converted with `mode=pages`: the worker's page images are gone
            with _PDFIUM:
                page_book(Path(file.path), options, folder, lambda event: None, lambda: False, [])

    # Folders

    def _folder(self, info: JobInfo, n: int, name: str) -> Path:
        """The cache folder `<job>/preview/<n>/<name>`, made now if need be. It is made one level
        at a time inside the job's folder, never with the job's folder itself: a request that
        comes in while its job is deleted or purged must not make the job's folder again. 404
        when the job is gone."""
        try:
            folder = self._store.job_dir(info.id)
            for part in ("preview", str(n), name):
                folder /= part
                folder.mkdir(exist_ok=True)
        except (KeyError, FileNotFoundError):
            raise PreviewError(404, STRINGS["error_job"]) from None
        return folder

    @contextmanager
    def _job_kept(self, info: JobInfo) -> Iterator[None]:
        """Whatever goes wrong in the block is 404 `No such job` when the job has gone meanwhile:
        deleted by its user, or purged."""
        try:
            yield
        except Exception:
            if not (self._store.root / info.id / "job.json").is_file():
                raise PreviewError(404, STRINGS["error_job"]) from None
            raise

    @contextmanager
    def _hold(self, folder: Path) -> Iterator[None]:
        """One thread at a time works in a cache folder."""
        with self._guard:
            lock = self._locks.get(folder)
            if lock is None:
                lock = self._locks[folder] = threading.Lock()
        with lock:
            yield
