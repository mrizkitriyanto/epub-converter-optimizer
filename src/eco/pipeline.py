"""The conversion pipeline: a PDF, Markdown file, book folder or EPUB in, an EPUB out.

Everything the core reports goes through `on_event`. A PDF is extracted once: the book folder of
the extraction stays in the data folder and is reused while the PDF and the extraction options are
the same, so changing an output option never runs Docling or OCR again."""

import hashlib
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from eco.book import Block, Book
from eco.bookfolder import load_source, read_report, write_book
from eco.epub.builder import build_epub
from eco.epub.optimizer import optimize_epub
from eco.events import Cancelled, Event, Finding, FindingEvent, PageEvent, StageEvent
from eco.models import models_dir
from eco.options import DEVICES, Options, image_profile
from eco.pdf.code import fix_code_blocks
from eco.pdf.docling_adapter import extract_blocks
from eco.pdf.pages import PageInfo, PdfOpenError, bookmarks, inspect_pdf, pdf_metadata
from eco.pdf.reading_order import fix_reading_order
from eco.pdf.regions import _save_by_content, materialize_regions, page_slices, render_cover
from eco.pdf.structure import assign_heading_levels
from eco.pdf.text import (
    clean_heading_artifacts,
    dehyphenate,
    detect_language,
    join_split_paragraphs,
    normalize,
)

EXTRACTOR_VERSION = 4  # bump it when extraction changes: cached book folders then stop matching
CHUNK_PAGES = 50
_LANGUAGE_SAMPLE = 5000


@dataclass
class Result:
    source: Path
    outputs: dict[str, Path]  # format -> file
    book_dir: Path | None  # the book folder the EPUB was built from, if one stays on disk
    findings: list[Finding]
    seconds: float
    sizes: dict[str, int]  # format -> bytes of the output


@contextmanager
def _stage(on_event: Callable[[Event], None], name: str):
    on_event(StageEvent(name, "started"))
    yield
    on_event(StageEvent(name, "finished"))


def _add(findings: list[Finding], new: list[Finding], on_event: Callable[[Event], None]) -> None:
    for finding in new:
        findings.append(finding)
        on_event(FindingEvent(finding))


def _same_file(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and a.samefile(b))


def output_path(
    src: Path, out_dir: Path, device: str, ext: str, inputs: Sequence[Path] = ()
) -> Path:
    """`out_dir/<stem>.<device>.<ext>`, with -1, -2... added to the name until it is no input.

    A stem that already ends in `.<device>` (the output of an earlier run) loses that ending
    first, so converting `book.x4.epub` again gives `book.x4-1.epub` and not `book.x4.x4.epub`.
    """
    stem = src.stem.removesuffix(f".{device}")
    n = 0
    while True:
        path = out_dir / f"{stem}.{device}{f'-{n}' if n else ''}.{ext}"
        if not any(_same_file(path, other) for other in inputs):
            return path
        n += 1


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _read(
    pdf: Path, ocr: bool, on_event: Callable[[Event], None], findings: list[Finding]
) -> list[PageInfo]:
    """The `read` stage: the pages of the PDF, and a finding for each blank or scanned one."""
    with _stage(on_event, "read"):
        infos = inspect_pdf(pdf)
        new = []
        for info in infos:
            if info.is_blank:
                new.append(Finding(info.number, "blank_page", "info", "Blank page skipped."))
            elif ocr and info.is_scanned:
                new.append(Finding(info.number, "ocr_page", "info", "Scanned page read with OCR."))
        _add(findings, new, on_event)
    return infos


def _chunks(numbers: list[int]) -> list[tuple[int, int]]:
    """(first, last) of each run of consecutive page numbers, cut to at most CHUNK_PAGES pages."""
    chunks: list[list[int]] = []
    for n in numbers:
        if chunks and n == chunks[-1][1] + 1 and n - chunks[-1][0] < CHUNK_PAGES:
            chunks[-1][1] = n
        else:
            chunks.append([n, n])
    return [(first, last) for first, last in chunks]


def _layout(
    pdf: Path,
    options: Options,
    models: Path,
    infos: list[PageInfo],
    on_event: Callable[[Event], None],
    cancel: Callable[[], bool],
    findings: list[Finding],
) -> list[Block]:
    """The `layout` stage: Docling over the non-blank pages, one chunk at a time."""
    numbers = [info.number for info in infos if not info.is_blank]
    scanned = frozenset(info.number for info in infos if info.is_scanned)
    reported: set[int] = set()

    def on_page(number: int) -> None:
        reported.add(number)
        on_event(PageEvent(len(reported), len(numbers)))

    blocks: list[Block] = []
    for first, last in _chunks(numbers):
        # ponytail: Docling swallows an exception raised in its progress callback, so a request
        # to cancel takes effect only between chunks. The web GUI stops a worker process instead.
        if cancel():
            raise Cancelled
        blocks += extract_blocks(
            pdf, models, first=first, last=last, ocr=options.ocr, on_page=on_page, scanned=scanned
        )
        message = "This page could not be converted and is missing from the book."
        failed = [
            Finding(n, "page_failed", "warning", message)
            for n in range(first, last + 1)
            if n not in reported
        ]
        _add(findings, failed, on_event)
    if cancel():
        raise Cancelled
    return blocks


def _fix(
    pdf: Path,
    blocks: list[Block],
    pages: dict[int, PageInfo],
    images_dir: Path,
    language: str,
    on_event: Callable[[Event], None],
    findings: list[Finding],
) -> list[Block]:
    """The passes of the `fix` stage. Their order matters."""
    blocks, found = fix_reading_order(blocks, pages)
    _add(findings, found, on_event)
    blocks, found = fix_code_blocks(pdf, blocks, pages, images_dir)
    _add(findings, found, on_event)
    blocks, found = materialize_regions(pdf, blocks, pages, images_dir)
    _add(findings, found, on_event)
    # normalize collapses runs of spaces, which would undo the indentation of a code block
    blocks = [b if b.kind == "code" else replace(b, text=normalize(b.text)) for b in blocks]
    # joining first turns a word hyphenated across a page break into a word that dehyphenate fixes
    blocks = join_split_paragraphs(blocks)
    blocks, _ = dehyphenate(blocks)
    blocks = [
        replace(b, text=clean_heading_artifacts(b.text, language))
        if b.kind == "heading" and b.ocr
        else b
        for b in blocks
    ]
    blocks, found = assign_heading_levels(blocks, bookmarks(pdf))
    _add(findings, found, on_event)
    return blocks


def _pdf_book(pdf: Path, digest: str, language: str, blocks: list[Block], folder: Path) -> Book:
    """The book of a PDF. Its metadata comes from the PDF alone, never from the user's options:
    those are applied at build time, so they are not part of what the cache holds."""
    meta = pdf_metadata(pdf)
    return Book(
        title=meta.get("title", pdf.stem),
        author=meta.get("author", ""),
        language=language,
        source=f"{pdf.name} sha256:{digest}",
        cover=render_cover(pdf, folder / "images"),
        blocks=blocks,
    )


def extract_pdf(
    pdf: Path,
    options: Options,
    *,
    data_dir: Path,
    on_event: Callable[[Event], None],
    cancel: Callable[[], bool],
) -> Path:
    """Extract a PDF into a book folder of the cache and return the folder.

    The folder is named after the PDF's SHA-256, the extractor version and `options.ocr`. One that
    holds a report.json and a book.md is complete: it is reused, and only its findings are reported
    again. One without book.md, which a virus scanner can remove, is extracted again. The stages
    are `read`, `layout` and `fix`. Raises PdfOpenError for a PDF that cannot be read,
    ModelsMissing when `eco setup` has not run, Cancelled when `cancel()` says so and
    RemovedByAntivirus when Windows refuses to write book.md.
    """
    try:
        digest = _sha256(pdf)
    except OSError as error:  # the same message inspect_pdf gives for a file it cannot open
        raise PdfOpenError(f"Not a readable PDF: {pdf.name}") from error
    folder = data_dir / "cache" / f"{digest[:16]}-x{EXTRACTOR_VERSION}-{options.ocr}.book"
    if (folder / "report.json").is_file() and (folder / "book.md").is_file():
        for finding in read_report(folder):
            on_event(FindingEvent(finding))
        return folder
    shutil.rmtree(folder, ignore_errors=True)  # a run that was cancelled or crashed left it, or
    # a virus scanner removed its book.md

    findings: list[Finding] = []
    infos = _read(pdf, options.ocr != "off", on_event, findings)
    with _stage(on_event, "layout"):
        blocks = _layout(pdf, options, models_dir(data_dir), infos, on_event, cancel, findings)
    with _stage(on_event, "fix"):
        text = " ".join(b.text for b in blocks)[:_LANGUAGE_SAMPLE]
        language = detect_language(text)
        pages = {info.number: info for info in infos}
        blocks = _fix(pdf, blocks, pages, folder / "images", language, on_event, findings)
        write_book(_pdf_book(pdf, digest, language, blocks, folder), folder, findings)
    return folder


def _page_book(
    pdf: Path,
    options: Options,
    folder: Path,
    on_event: Callable[[Event], None],
    cancel: Callable[[], bool],
    findings: list[Finding],
) -> Path:
    """`--mode pages`: a book folder of images, one for each screen of every non-blank page."""
    infos = _read(pdf, False, on_event, findings)
    # a general e-reader has no fixed screen: a page keeps its whole height, as one image
    screen = DEVICES[options.device] or (image_profile(options).max_w, 100_000)
    numbers = [info.number for info in infos if not info.is_blank]
    blocks = []
    with _stage(on_event, "layout"):
        for done, number in enumerate(numbers, 1):
            if cancel():
                raise Cancelled
            for k, im in enumerate(page_slices(pdf, number, screen, options.landscape), 1):
                image = _save_by_content(im, folder / "images", f"p{number:04d}-slice-{k}")
                blocks.append(Block("image", f"Page {number}", page=number, image=image))
            on_event(PageEvent(done, len(numbers)))
    write_book(_pdf_book(pdf, _sha256(pdf), "en", blocks, folder), folder, findings)
    return folder


def _override(meta: dict[str, str], options: Options) -> None:
    """The title, author and language the user asked for win over the book's own."""
    for key, value in (
        ("title", options.title),
        ("author", options.author),
        ("language", options.lang),
    ):
        if value:
            meta[key] = value


def convert_file(
    path: Path,
    options: Options,
    out_dir: Path,
    *,
    data_dir: Path,
    on_event: Callable[[Event], None] = lambda e: None,
    cancel: Callable[[], bool] = lambda: False,
    inputs: Sequence[Path] = (),
) -> Result:
    """Convert a PDF, Markdown file, book folder or EPUB into an EPUB in `out_dir`.

    `inputs` are all the files of the batch: the output never takes the name of one of them. A PDF
    goes through `extract_pdf` first (or, with `--mode pages`, becomes images of its pages), and
    every source but an EPUB is built into an EPUB before the optimizer runs. In M1 `--mode
    reflow` is the same as `auto`.

    Raises ValueError for an input of another kind, and what `extract_pdf` and the optimizer raise:
    PdfOpenError, ModelsMissing, Cancelled, RemovedByAntivirus (book.md cannot be written or
    read), DRMError.
    """
    start = time.monotonic()
    kind = "book" if path.is_dir() else path.suffix.lower().lstrip(".")
    if kind not in ("book", "pdf", "md", "epub"):
        raise ValueError(f"Unsupported input: {path.name}")
    findings: list[Finding] = []
    book_dir = path if kind == "book" else None
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        if kind == "epub":
            built = path
        else:
            if kind == "pdf" and options.mode == "pages":
                source_path = _page_book(
                    path, options, scratch / "pages.book", on_event, cancel, findings
                )
            elif kind == "pdf":
                book_dir = source_path = extract_pdf(
                    path, options, data_dir=data_dir, on_event=on_event, cancel=cancel
                )
                findings += read_report(book_dir)  # extract_pdf has reported them already
            else:
                source_path = path
            source = load_source(source_path)
            if kind == "pdf" and "title" not in pdf_metadata(path):
                # the cache serves every file with these bytes, so the file name it saw first
                # must not become the title of a copy that has another name
                source.meta["title"] = path.stem
            _override(source.meta, options)
            built = scratch / "built.epub"
            with _stage(on_event, "epub"):
                _add(findings, build_epub(source, built, device=options.device), on_event)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = output_path(path, out_dir, options.device, "epub", (*inputs, path))
        with _stage(on_event, "optimize"):
            _add(findings, optimize_epub(built, out, options).findings, on_event)
    seconds = time.monotonic() - start
    return Result(path, {"epub": out}, book_dir, findings, seconds, {"epub": out.stat().st_size})
