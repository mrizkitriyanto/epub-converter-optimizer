"""The preview API: the original PDF page, the device pages, the live preview and the book text.

A job is made in the store without a worker: a preview needs the job's uploads and the word that a
file was converted (its `outputs`), nothing else. One test runs the real worker from end to end.
"""

import gc
import io
import json
import pkgutil
import shutil
import struct
import threading
import time
import weakref
import zlib
from dataclasses import fields, replace
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from fakes import wait_for
from fastapi.testclient import TestClient
from fixtures.make import image_bytes, make_epub
from PIL import Image, ImageFile
from pypdf import PdfReader, PdfWriter

from eco.options import Options, image_profile
from eco.render.pages import Rendered
from eco.style import CHOICES, RANGES, PageStyle
from eco.web.app import create_app
from eco.web.preview import PreviewError, _style_key

LOCAL = "http://127.0.0.1:8000"  # a browser on this computer, server on the default port
NO_PAGE = {"error": "No such page"}
NOT_CONVERTED = {"error": "This file has not been converted yet"}
NO_PREVIEW = {"error": "No preview is available for this file"}
NO_TEXT = {"error": "This file has no text to show"}
TWO = b"# One\n\nFirst chapter text.\n\n# Two\n\nSecond chapter text.\n"
# Chapter One is one page and chapter Two takes several, so the number of pages tells them apart.
LONG = (
    "# One\n\nFirst chapter text.\n\n# Two\n\n"
    + "\n\n".join(
        f"Paragraph {n} of the second chapter, with enough words to fill a few lines."
        for n in range(1, 41)
    )
    + "\n"
).encode()


# Helpers


@pytest.fixture
def app(tmp_path):
    """The app on tmp_path without its lifespan: no runner thread, so a job stays as it is made."""
    return create_app(tmp_path, token=None)


@pytest.fixture
def c(app):
    return TestClient(app, base_url=LOCAL)


@pytest.fixture
def three_pages(fixtures_dir):
    """A PDF of three pages: text, nothing, text."""
    return fixtures_dir["blank"].read_bytes()


@pytest.fixture
def three_pictures(fixtures_dir):
    """A PDF of three pages that are each one picture, so that each page of its pages-mode book
    fills a device page."""
    page = PdfReader(fixtures_dir["photo"][0]).pages[0]
    writer = PdfWriter()
    for _ in range(3):
        writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def make_job(app, *files, options=None, converted=True, book_dir=None):
    """A job made without a worker; `files` are (name, bytes). A converted file has an output
    (the previews never read it). `book_dir` is the book folder of the first file, as a PDF that
    was converted by reflow has."""
    store = app.state.store
    info = store.create([(name, io.BytesIO(data)) for name, data in files], options or Options())
    for n, f in enumerate(info.files):
        if converted:
            out = store.job_dir(info.id) / "output" / f"{n}.x4.epub"
            out.write_bytes(b"an EPUB")
            f.outputs = {"epub": str(out)}
    if book_dir:
        info.files[0].book_dir = str(book_dir)
    info.status = "done" if converted else "queued"
    store.save(info)
    return info


def url(job, tail, n=0):
    return f"/api/jobs/{job.id}/files/{n}/{tail}"


def style_folder(view, style=None, fmt="epub"):
    """The name of the folder of the device pages that a style is rendered into."""
    return f"{fmt}-{view}-{_style_key(style or PageStyle())}"


def cache(app, job, n, *parts):
    """A folder or file of the job's preview cache."""
    return app.state.store.job_dir(job.id).joinpath("preview", str(n), *parts)


def image(response) -> Image.Image:
    return Image.open(BytesIO(response.content))


def body(response) -> bytes:
    """The pixels of a page above its footer. The footer counts the pages of what was rendered, so
    a chapter alone and the whole book differ there and nowhere else."""
    return image(response).crop((0, 0, 480, 740)).tobytes()


def counting(monkeypatch, target):
    """Count the calls of a function, given as a dotted name, and keep their keyword arguments.
    The calls still run."""
    real = pkgutil.resolve_name(target)
    calls = []

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(target, spy)
    return calls


def small_png(n) -> bytes:
    out = BytesIO()
    Image.new("L", (4, 4), n).save(out, "PNG")
    return out.getvalue()


def pdf_of(width, height) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def tiny_epub(tmp_path, page_body, extra=None) -> bytes:
    """An EPUB of one XHTML page, plus the files in `extra`."""
    container = (
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Tiny</dc:title>'
        '<dc:language>en</dc:language></metadata><manifest><item id="c0" href="c0.xhtml" '
        'media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c0"/></spine>'
        "</package>"
    )
    page = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
        f"<body>{page_body}</body></html>"
    )
    files = {"META-INF/container.xml": container, "OEBPS/content.opf": opf, "OEBPS/c0.xhtml": page}
    return make_epub(tmp_path / "tiny.epub", {**files, **(extra or {})}).read_bytes()


def solid_png(width, height) -> bytes:
    """A grey PNG of width x height pixels, made chunk by chunk so that making it holds no raster
    (PIL would hold all of it). It compresses to about a thousandth of its pixels."""

    def chunk(kind, data):
        framed = kind + data
        return struct.pack(">I", len(data)) + framed + struct.pack(">I", zlib.crc32(framed))

    row = b"\x00" + b"\x80" * width
    packer = zlib.compressobj(1)
    data = b"".join(packer.compress(row) for _ in range(height)) + packer.flush()
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", data) + chunk(b"IEND", b"")
    )


def assert_no_path(documents, root: Path):
    """No JSON document (a parsed value) holds the data folder, or any absolute path at all."""
    forms = [str(root), str(root).replace("\\", "\\\\"), root.as_posix()]
    seen = []

    def strings(value):
        if isinstance(value, str):
            seen.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                strings(key)
                strings(item)
        elif isinstance(value, list):
            for item in value:
                strings(item)

    for document in documents:
        text = json.dumps(document, ensure_ascii=False)
        assert not any(form in text for form in forms), text
        strings(document)
    for found in seen:
        assert not PurePosixPath(found).is_absolute(), found
        assert not PureWindowsPath(found).is_absolute(), found


# The main preview: pages, and one device page


def test_pages_of_a_finished_markdown_job(c, app):
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, "pages?format=epub&view=crosspoint"))
    assert r.status_code == 200
    answer = r.json()
    assert list(answer) == ["source_pages", "device_pages", "page_map", "chapters"]
    assert answer["source_pages"] == 0  # not a PDF
    assert answer["device_pages"] > 0
    assert answer["page_map"] == [0] * answer["device_pages"]  # Markdown has no page markers
    assert answer["chapters"] == [["One", 1], ["Two", 2]]


def test_format_and_view_have_defaults(c, app):
    job = make_job(app, ("book.md", TWO))
    assert c.get(url(job, "pages")).json() == c.get(url(job, "pages?view=crosspoint")).json()
    assert c.get(url(job, "preview/epub/1.png")).status_code == 200


def test_a_device_page_is_a_480_by_800_png(c, app):
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, "preview/epub/1.png?view=stock"))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert (image(r).format, image(r).size, image(r).mode) == ("PNG", (480, 800), "L")


def test_a_page_that_does_not_exist_is_404(c, app):
    job = make_job(app, ("book.md", TWO))
    count = c.get(url(job, "pages")).json()["device_pages"]
    assert c.get(url(job, f"preview/epub/{count}.png")).status_code == 200
    for page in (count + 1, 9999, 0):
        r = c.get(url(job, f"preview/epub/{page}.png"))
        assert (r.status_code, r.json()) == (404, NO_PAGE)


@pytest.mark.parametrize("page", ["01", "+1", "-1", "x", "1.5", "1000000"])
def test_a_page_number_must_be_a_plain_number(c, app, page):
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, f"preview/epub/{page}.png"))
    assert (r.status_code, r.json()) == (404, NO_PAGE)


@pytest.mark.parametrize(
    "tail, message",
    [
        ("pages?view=kindle", "Unknown view: kindle"),
        ("preview/epub/1.png?view=kindle", "Unknown view: kindle"),
        ("pages?view=xtc", "Unknown view: xtc"),  # XTC output comes with M3
        ("preview/epub/1.png?view=xtc", "Unknown view: xtc"),
        ("pages?view=CrossPoint", "Unknown view: CrossPoint"),
        ("pages?view=", "Unknown view: "),
        ("pages?format=xtc", "Unknown format: xtc"),
        ("preview/xtc/1.png", "Unknown format: xtc"),
        ("preview/pdf/1.png", "Unknown format: pdf"),
    ],
)
def test_an_unknown_view_or_format_is_400(c, app, tail, message):
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, tail))
    assert (r.status_code, r.json()) == (400, {"error": message})


def test_the_three_views_are_accepted(c, app):
    job = make_job(app, ("book.md", TWO))
    for view in ("crosspoint", "crossink", "stock"):
        assert c.get(url(job, f"preview/epub/1.png?view={view}")).status_code == 200
        assert (cache(app, job, 0, style_folder(view)) / "map.json").is_file()


def test_an_invalid_request_is_checked_before_the_state_of_the_file(c, app):
    job = make_job(app, ("book.md", TWO), converted=False)
    r = c.get(url(job, "pages?view=kindle"))
    assert (r.status_code, r.json()) == (400, {"error": "Unknown view: kindle"})


def test_numbering_is_one_based_everywhere(c, app, small_book, three_pages):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=small_book)
    assert c.get(url(job, "pages")).json() == {
        "source_pages": 3,
        "device_pages": 2,
        "page_map": [1, 3],  # the source page of device page 1 and of device page 2
        "chapters": [["One", 1], ["Two", 2]],  # the first device page of each chapter
    }
    assert c.get(url(job, "preview/epub/0.png")).status_code == 404
    assert c.get(url(job, "preview/epub/1.png")).status_code == 200
    assert c.get(url(job, "preview/epub/2.png")).status_code == 200
    assert c.get(url(job, "preview/epub/3.png")).status_code == 404


def test_a_page_before_the_first_marker_has_source_page_0(c, app, tmp_path, three_pages):
    book = tmp_path / "x.book"
    book.mkdir()
    (book / "book.md").write_text("intro\n\n# One\n\ntext\n\n<!-- page: 3 -->\n\nmore\n")
    job = make_job(app, ("scan.pdf", three_pages), book_dir=book)
    assert c.get(url(job, "pages")).json()["page_map"] == [0, 3]


def test_the_cache_of_a_file_is_under_its_own_number(c, app):
    alpha = b"# Alpha\n\ntext\n"
    beta = b"# Beta\n\ntext\n\n# Gamma\n\nmore\n"
    job = make_job(app, ("a.md", alpha), ("b.md", beta))
    assert c.get(url(job, "pages", 0)).json()["chapters"] == [["Alpha", 1]]
    assert c.get(url(job, "pages", 1)).json()["chapters"] == [["Beta", 1], ["Gamma", 2]]
    first = c.get(url(job, "preview/epub/1.png", 0))
    assert first.content != c.get(url(job, "preview/epub/1.png", 1)).content
    folder = app.state.store.job_dir(job.id) / "preview"
    assert sorted(p.name for p in folder.iterdir()) == ["0", "1"]
    assert (
        cache(app, job, 0, style_folder("crosspoint")) / "0001.png"
    ).read_bytes() == first.content
    assert (cache(app, job, 1, style_folder("crosspoint")) / "0002.png").is_file()


def test_the_main_preview_renders_with_the_jobs_own_options(c, app, monkeypatch):
    options = Options(device="x3", size="small", firmware="stock", style=PageStyle(font_size=48))
    job = make_job(app, ("book.md", TWO), options=options)
    seen = counting(monkeypatch, "eco.web.preview.render_book")
    assert c.get(url(job, "pages?view=stock")).status_code == 200
    [kw] = seen
    assert (kw["device"], kw["view"]) == ("x3", "stock")
    assert kw["style"] == PageStyle(font_size=48)
    assert kw["image_profile"] == image_profile(options)
    assert kw["cache_dir"] == cache(app, job, 0, style_folder("stock", PageStyle(font_size=48)))
    assert image(c.get(url(job, "preview/epub/1.png?view=stock"))).size == (528, 792)


def test_a_bigger_font_makes_more_pages(c, app):
    big = make_job(app, ("a.md", LONG), options=Options(style=PageStyle(font_size=48)))
    small = make_job(app, ("a.md", LONG), options=Options(style=PageStyle(font_size=24)))
    pages = {"big": big, "small": small}
    count = {name: c.get(url(job, "pages")).json()["device_pages"] for name, job in pages.items()}
    assert count["big"] > count["small"]
    folder = style_folder("crosspoint", PageStyle(font_size=48))
    assert (cache(app, big, 0, folder) / "map.json").is_file()


def other_value(name, current):
    """A value for the field `name` of a style that is not `current` and is a valid one."""
    if name in RANGES:
        low, high = RANGES[name]
        return low if current != low else high
    if name in CHOICES:
        return next(value for value in CHOICES[name] if value != current)
    return {"font": "Bitter", "font_weight": 500, "lang": "de"}.get(name, not current)


def test_no_two_styles_share_a_cache_folder():
    base = PageStyle()
    keys = {_style_key(base)}
    for field in fields(PageStyle):  # every field changes what the pages look like
        other = replace(base, **{field.name: other_value(field.name, getattr(base, field.name))})
        keys.add(_style_key(other))
    assert len(keys) == len(fields(PageStyle)) + 1
    assert _style_key(PageStyle()) == _style_key(PageStyle())  # and an equal style has its folder


def test_an_epub_preview_simulates_the_style_of_the_job(c, app):
    plain = make_job(app, ("a.md", TWO))
    styled = make_job(
        app, ("a.md", TWO), options=Options(style=PageStyle(font="Bitter", align="left"))
    )
    assert (
        c.get(url(plain, "preview/epub/1.png")).content
        != c.get(url(styled, "preview/epub/1.png")).content
    )
    assert (
        c.get(url(plain, "live.png?chapter=0")).content
        != c.get(url(styled, "live.png?chapter=0")).content
    )


def test_an_epub_preview_is_not_turned(c, app):
    upright = make_job(app, ("a.md", TWO))
    turned = make_job(app, ("a.md", TWO), options=Options(style=PageStyle(orientation=90)))
    for tail in ("preview/epub/1.png", "live.png?chapter=0"):  # an EPUB has no orientation
        assert c.get(url(turned, tail)).content == c.get(url(upright, tail)).content
    assert (cache(app, turned, 0, style_folder("crosspoint")) / "map.json").is_file()


def test_a_second_request_does_not_render_again(c, app, monkeypatch):
    job = make_job(app, ("book.md", TWO))
    compiled = counting(monkeypatch, "typst.compile")
    c.get(url(job, "pages"))
    c.get(url(job, "preview/epub/1.png"))
    c.get(url(job, "preview/epub/2.png"))
    c.get(url(job, "pages"))
    assert len(compiled) == 1
    c.get(url(job, "preview/epub/1.png?view=stock"))  # another view is another cache folder
    assert len(compiled) == 2


def test_the_cache_is_on_the_disk_so_a_new_server_does_not_render_again(
    c, app, tmp_path, monkeypatch
):
    job = make_job(app, ("book.md", TWO))
    first = c.get(url(job, "preview/epub/2.png"))
    assert first.status_code == 200
    compiled = counting(monkeypatch, "typst.compile")
    new_server = TestClient(create_app(tmp_path, token=None), base_url=LOCAL)
    again = new_server.get(url(job, "preview/epub/2.png"))
    assert again.status_code == 200 and again.content == first.content
    assert compiled == []


def test_a_device_page_is_read_alone_not_with_the_whole_book(c, app, monkeypatch):
    warm, cold = make_job(app, ("book.md", LONG)), make_job(app, ("book.md", LONG))
    assert c.get(url(warm, "pages")).json()["device_pages"] > 4
    read = []
    real = Path.read_bytes

    def spy(self):
        read.append(self.name)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    assert c.get(url(warm, "preview/epub/3.png")).status_code == 200  # a warm cache
    assert c.get(url(cold, "preview/epub/2.png")).status_code == 200  # a cold one: rendered first
    assert [name for name in read if name.endswith(".png")] == ["0003.png", "0002.png"]


def test_two_threads_that_render_one_cache_folder_both_succeed(app, monkeypatch):
    job = make_job(app, ("book.md", LONG))
    real = pkgutil.resolve_name("typst.compile")
    compiles, inside = [], threading.Event()

    def slow_compile(*args, **kwargs):
        compiles.append(1)
        inside.set()
        time.sleep(0.5)  # the second thread arrives while the first one compiles
        return real(*args, **kwargs)

    monkeypatch.setattr("typst.compile", slow_compile)
    results = {}

    def fetch(name):
        results[name] = app.state.previews.device_page(job, 0, "epub", "crosspoint", 1)

    first = threading.Thread(target=fetch, args=("first",))
    second = threading.Thread(target=fetch, args=("second",))
    first.start()
    inside.wait(10)
    second.start()
    first.join(60)
    second.join(60)
    assert results["first"] == results["second"] and results["first"][:4] == b"\x89PNG"
    assert len(compiles) == 1  # the second one waited, then read what the first one wrote


# Source pages


def test_a_source_page_is_600_px_wide_as_soon_as_the_pdf_is_uploaded(c, app, three_pages):
    job = make_job(app, ("a.pdf", three_pages), converted=False)  # still queued
    r = c.get(url(job, "source/1.png"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    width, height = image(r).size
    assert width == 600 and abs(height - 600 * 792 / 612) <= 1
    assert image(r).mode == "RGB"  # the original keeps its colours
    assert image(c.get(url(job, "source/2.png"))).size == (width, height)  # the blank page too


def test_a_source_page_is_cached_in_the_job(c, app, three_pages, monkeypatch):
    job = make_job(app, ("a.pdf", three_pages))
    drawn = counting(monkeypatch, "eco.web.preview.render_page_fit")
    first = c.get(url(job, "source/3.png"))
    again = c.get(url(job, "source/3.png"))
    assert first.content == again.content and len(drawn) == 1
    assert cache(app, job, 0, "source", "3.png").read_bytes() == first.content


def test_source_pages_of_two_files_are_cached_apart(c, app, three_pages, fixtures_dir):
    other = fixtures_dir["two_column"][0].read_bytes()
    job = make_job(app, ("a.pdf", three_pages), ("b.pdf", other))
    a, b = c.get(url(job, "source/1.png", 0)), c.get(url(job, "source/1.png", 1))
    assert a.content != b.content
    assert cache(app, job, 0, "source", "1.png").read_bytes() == a.content
    assert cache(app, job, 1, "source", "1.png").read_bytes() == b.content


@pytest.mark.parametrize("page", ["4", "9999", "0", "01", "+1", "-1", "x", "1.5"])
def test_a_source_page_that_does_not_exist_is_404(c, app, three_pages, page):
    job = make_job(app, ("a.pdf", three_pages))
    r = c.get(url(job, f"source/{page}.png"))
    assert (r.status_code, r.json()) == (404, NO_PAGE)


@pytest.mark.parametrize("name, data", [("a.md", TWO), ("a.epub", b"PK")])
def test_a_file_that_is_not_a_pdf_has_no_source_pages(c, app, name, data):
    job = make_job(app, (name, data))
    r = c.get(url(job, "source/1.png"))
    assert (r.status_code, r.json()) == (404, {"error": "This file has no source pages"})


def test_a_very_tall_page_is_drawn_smaller_so_the_picture_stays_bounded(c, app):
    job = make_job(app, ("thin.pdf", pdf_of(1, 14400)), ("tall.pdf", pdf_of(400, 8000)))
    thin = c.get(url(job, "source/1.png", 0))
    assert thin.status_code == 200 and image(thin).size == (1, 6000)  # not 600 x 8,640,000
    tall = c.get(url(job, "source/1.png", 1))
    assert image(tall).size == (300, 6000)  # 600 wide would be 12,000 px tall


def test_a_pdf_that_cannot_be_read_has_no_source_pages_to_show(c, app):
    job = make_job(app, ("junk.pdf", b"not a pdf"), converted=False)
    r = c.get(url(job, "source/1.png"))
    assert (r.status_code, r.json()) == (422, {"error": "This PDF could not be read"})


def test_pages_counts_the_pages_of_the_pdf(c, app, small_book, three_pages):
    job = make_job(app, ("a.pdf", three_pages), book_dir=small_book)
    assert c.get(url(job, "pages")).json()["source_pages"] == 3


# State: nothing but the source pages is there before the conversion


@pytest.mark.parametrize("tail", ["pages", "preview/epub/1.png", "live.png?chapter=0", "text"])
def test_a_file_that_is_not_converted_has_no_preview_yet(c, app, tail):
    job = make_job(app, ("book.md", TWO), converted=False)
    r = c.get(url(job, tail))
    assert (r.status_code, r.json()) == (409, NOT_CONVERTED)


def test_a_file_that_failed_has_no_preview(c, app):
    job = make_job(app, ("book.md", TWO), converted=False)
    info = app.state.store.get(job.id)
    info.files[0].error = "boom"
    info.status = "failed"
    app.state.store.save(info)
    assert c.get(url(job, "pages")).status_code == 409


def test_only_the_converted_file_of_a_job_has_a_preview(c, app):
    job = make_job(app, ("a.md", TWO), ("b.md", TWO))
    info = app.state.store.get(job.id)
    info.files[1].outputs = {}
    app.state.store.save(info)
    assert c.get(url(job, "pages", 0)).status_code == 200
    assert c.get(url(job, "pages", 1)).status_code == 409


TAILS = ["pages", "source/1.png", "preview/epub/1.png", "live.png?chapter=0", "text"]


@pytest.mark.parametrize("tail", TAILS)
@pytest.mark.parametrize("n", ["1", "-1", "x", "00", "%2B0", "99999999999999999999"])
def test_a_file_that_is_not_in_the_job_is_404(c, app, tail, n):
    job = make_job(app, ("book.md", TWO))
    r = c.get(f"/api/jobs/{job.id}/files/{n}/{tail}")
    assert (r.status_code, r.json()) == (404, {"error": "No such file in this job"})


@pytest.mark.parametrize("tail", TAILS)
def test_a_job_that_does_not_exist_is_404(c, tail):
    r = c.get(f"/api/jobs/0123456789abcdef/files/0/{tail}")
    assert (r.status_code, r.json()) == (404, {"error": "No such job"})


# A job deleted (ruling M2-R45) or purged while its preview is asked for


GONE = {"error": "No such job"}


@pytest.fixture
def previewed(app, three_pages, three_pictures, tmp_path):
    """Jobs of each kind of book, by name: the job and the way its preview is asked for."""
    epub = tiny_epub(tmp_path, "<h1>Alpha</h1><p>Hello.</p>")
    return {
        "source": (make_job(app, ("scan.pdf", three_pages)), "source/1.png"),
        "markdown": (make_job(app, ("book.md", TWO)), "pages"),
        "epub": (make_job(app, ("t.epub", epub)), "pages"),
        "pages-mode": (
            make_job(app, ("scan.pdf", three_pictures), options=Options(mode="pages")),
            "live.png?chapter=0",
        ),
    }


@pytest.mark.parametrize("kind", ["source", "markdown", "epub", "pages-mode"])
def test_a_preview_that_comes_after_its_job_went_does_not_make_the_job_again(app, previewed, kind):
    job, tail = previewed[kind]
    folder = app.state.store.job_dir(job.id)
    shutil.rmtree(folder)  # the route had found the job; then it was deleted
    previews = app.state.previews
    with pytest.raises(PreviewError) as caught:
        if tail.startswith("source"):
            previews.source_page(job, 0, 1)
        elif tail == "pages":
            previews.pages(job, 0, "epub", "crosspoint")
        else:
            previews.live(
                job, 0, "epub", "crosspoint", font_size=None, size=None, page=None, chapter=0
            )
    assert (caught.value.status, caught.value.message) == (404, GONE["error"])
    assert not folder.exists()
    others = {j.id for j, _ in previewed.values()} - {job.id}
    assert {p.name for p in app.state.store.root.iterdir()} == others


@pytest.mark.parametrize(
    "kind, target",
    [
        ("markdown", "eco.web.preview.render_book"),  # the job goes while its pages are rendered
        ("epub", "eco.web.preview.epub_to_book"),  # while its book is read
        ("pages-mode", "eco.web.preview.page_book"),  # while its page images are made
        ("source", "eco.web.preview.render_page_fit"),  # while a PDF page is drawn
    ],
)
def test_a_job_that_goes_while_its_preview_is_made_is_404_and_stays_gone(
    c, app, previewed, monkeypatch, kind, target
):
    job, tail = previewed[kind]
    folder = app.state.store.job_dir(job.id)
    real = pkgutil.resolve_name(target)

    def deleted_first(*args, **kwargs):
        shutil.rmtree(folder)
        return real(*args, **kwargs)

    monkeypatch.setattr(target, deleted_first)
    r = c.get(url(job, tail))
    assert (r.status_code, r.json()) == (404, GONE)
    assert not folder.exists()
    others = {j.id for j, _ in previewed.values()} - {job.id}
    assert {p.name for p in app.state.store.root.iterdir()} == others  # no folder of the build


# Pages-mode PDFs: their book is built on first use


def test_a_pages_mode_pdf_is_previewed_from_a_book_built_on_first_use(
    c, app, three_pictures, monkeypatch
):
    job = make_job(app, ("scan.pdf", three_pictures), options=Options(mode="pages"))
    assert app.state.store.get(job.id).files[0].book_dir is None  # as the worker leaves it
    built = counting(monkeypatch, "eco.web.preview.page_book")
    answer = c.get(url(job, "pages")).json()
    assert answer["source_pages"] == 3
    assert answer["page_map"] == [1, 2, 3]  # a picture to a device page
    assert answer["chapters"] == []  # page images have no headings
    assert (cache(app, job, 0, "book") / "book.md").is_file()
    assert len(list((cache(app, job, 0, "book") / "images").glob("p*-slice-*"))) == 3
    assert image(c.get(url(job, "preview/epub/2.png"))).size == (480, 800)
    assert len(built) == 1  # once


def test_the_page_book_of_a_pages_mode_pdf_has_no_page_for_a_blank_page(c, app, three_pages):
    job = make_job(app, ("scan.pdf", three_pages), options=Options(mode="pages"))
    answer = c.get(url(job, "pages")).json()
    assert answer["source_pages"] == 3
    assert answer["page_map"] == [3]  # both pictures are small: one page, the last marker wins
    book = (cache(app, job, 0, "book") / "book.md").read_text(encoding="utf-8")
    assert "<!-- page: 1 -->" in book and "<!-- page: 2 -->" not in book


def test_the_page_book_of_a_pages_mode_pdf_follows_the_jobs_options(c, app, three_pictures):
    options = Options(mode="pages", device="x3")
    job = make_job(app, ("scan.pdf", three_pictures), options=options)
    c.get(url(job, "pages"))
    pictures = sorted((cache(app, job, 0, "book") / "images").glob("p*-slice-*"))
    assert len(pictures) == 3
    with Image.open(pictures[0]) as im:
        assert im.width == 528  # a screen of the x3, not of the x4


def test_a_pages_mode_pdf_is_one_chapter_for_the_live_preview(c, app, three_pictures):
    job = make_job(app, ("scan.pdf", three_pictures), options=Options(mode="pages"))
    whole = c.get(url(job, "live.png?chapter=0"))
    assert (whole.headers["x-excerpt-index"], whole.headers["x-excerpt-pages"]) == ("0", "3")
    page = c.get(url(job, "live.png?page=3"))  # source page 3 is the third page of the book
    assert (page.headers["x-excerpt-index"], page.headers["x-excerpt-pages"]) == ("2", "3")
    assert c.get(url(job, "live.png?chapter=1")).status_code == 404  # the one chapter is 0


def test_a_pages_mode_pdf_has_no_text(c, app, three_pages):
    job = make_job(app, ("scan.pdf", three_pages), options=Options(mode="pages"))
    r = c.get(url(job, "text"))
    assert (r.status_code, r.json()) == (404, NO_TEXT)


def test_a_reflow_pdf_whose_book_folder_is_gone_has_no_preview(c, app, three_pages, tmp_path):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=tmp_path / "gone.book")
    for tail, answer in (
        ("pages", NO_PREVIEW),
        ("preview/epub/1.png", NO_PREVIEW),
        ("live.png?page=1", NO_PREVIEW),
        ("text", NO_TEXT),
    ):
        r = c.get(url(job, tail))
        assert (r.status_code, r.json()) == (404, answer), tail
    assert c.get(url(job, "source/1.png")).status_code == 200  # the PDF itself is there


# EPUB inputs: read into a book folder on first use


def test_an_epub_is_read_into_a_book_once_and_previewed(c, app, tmp_path, monkeypatch):
    epub = tiny_epub(tmp_path, "<h1>Alpha</h1><p>Hello there.</p><h1>Beta</h1><p>More.</p>")
    job = make_job(app, ("t.epub", epub))
    read = counting(monkeypatch, "eco.web.preview.epub_to_book")
    answer = c.get(url(job, "pages")).json()
    assert (answer["source_pages"], answer["chapters"]) == (0, [["Alpha", 1], ["Beta", 2]])
    assert c.get(url(job, "live.png?chapter=1")).status_code == 200  # the book is used again
    assert c.get(url(job, "text")).status_code == 200
    assert len(read) == 1
    assert (cache(app, job, 0, "book") / "book.md").is_file()


def test_the_pictures_of_an_epub_are_in_its_preview(c, app, tmp_path):
    page = '<h1>Alpha</h1><p>Before.</p><p><img src="pic.png" alt="A picture"/></p>'
    plain = make_job(app, ("a.epub", tiny_epub(tmp_path, page.replace("pic.png", "none.png"))))
    picture = tiny_epub(tmp_path, page, extra={"OEBPS/pic.png": image_bytes((200, 120), "PNG")})
    shown = make_job(app, ("b.epub", picture))
    without = c.get(url(plain, "preview/epub/1.png"))
    with_picture = c.get(url(shown, "preview/epub/1.png"))
    assert without.status_code == with_picture.status_code == 200
    assert without.content != with_picture.content  # the picture is on the page
    assert len(list((cache(app, shown, 0, "book") / "images").iterdir())) == 1


def test_a_publisher_epub_with_every_kind_of_image_is_previewed(c, app, messy_epub):
    job = make_job(app, ("messy.epub", messy_epub.read_bytes()))
    # its first chapter holds the pictures (the whole book is hundreds of pages: see `pages`)
    live = c.get(url(job, "live.png?chapter=0"))
    assert live.status_code == 200 and image(live).size == (480, 800)
    assert "# Chapter One" in c.get(url(job, "text")).text


def test_an_epub_that_cannot_be_read_has_no_preview(c, app):
    job = make_job(app, ("bad.epub", b"PK not a zip"))
    r = c.get(url(job, "pages"))
    assert (r.status_code, r.json()) == (404, NO_PREVIEW)
    r = c.get(url(job, "text"))
    assert (r.status_code, r.json()) == (404, NO_TEXT)


def test_a_book_left_by_a_failed_read_is_built_again(c, app, tmp_path):
    job = make_job(app, ("t.epub", b"PK not a zip"))
    assert c.get(url(job, "pages")).status_code == 404
    Path(app.state.store.get(job.id).files[0].path).write_bytes(
        tiny_epub(tmp_path, "<h1>Alpha</h1><p>Hello.</p>")
    )
    assert c.get(url(job, "pages")).json()["chapters"] == [["Alpha", 1]]


# The book text


def test_a_markdown_job_gives_its_text(c, app):
    text = "---\ntitle: Bab Ü\n---\n\n# Bab Ü\n\nIsi bab satu & <b>lagi</b>.\n"
    job = make_job(app, ("book.md", text.encode()))
    r = c.get(url(job, "text"))
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.content == text.encode()


def test_an_epub_job_gives_the_text_of_its_chapters(c, app, tmp_path):
    epub = tiny_epub(
        tmp_path, "<h1>Alpha</h1><p>Hello <em>there</em>.</p><h1>Beta</h1><p>More.</p>"
    )
    job = make_job(app, ("t.epub", epub))
    r = c.get(url(job, "text"))
    assert r.status_code == 200 and r.headers["content-type"] == "text/plain; charset=utf-8"
    text = r.text.replace("\r\n", "\n")  # the book is written in text mode: CRLF on Windows
    assert "# Alpha\n\nHello *there*." in text and "# Beta\n\nMore." in text


def test_the_text_of_an_epub_names_the_upload_as_it_was_uploaded(c, app, tmp_path):
    job = make_job(app, ("novel.epub", tiny_epub(tmp_path, "<h1>Alpha</h1><p>Text.</p>")))
    text = c.get(url(job, "text")).text.replace("\r\n", "\n")
    assert 'source: "novel.epub"\n' in text  # where epub_to_book writes the name of what it read
    assert "0-novel" not in text


def test_a_reflow_pdf_job_gives_the_text_of_its_book(c, app, small_book, three_pages):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=small_book)
    r = c.get(url(job, "text"))
    assert r.status_code == 200
    assert r.content == (small_book / "book.md").read_bytes()  # the file as it is
    assert "<!-- page: 2 -->" in r.text


def test_the_text_is_never_served_as_html(c, app):
    job = make_job(app, ("book.md", b"<script>alert(1)</script>\n"))
    r = c.get(url(job, "text"))
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["x-content-type-options"] == "nosniff"


# The live preview


def test_live_font_size_changes_the_page(c, app):
    job = make_job(app, ("book.md", LONG))
    small = c.get(url(job, "live.png?chapter=1&font_size=24"))
    large = c.get(url(job, "live.png?chapter=1&font_size=40"))
    assert small.status_code == large.status_code == 200
    assert small.headers["content-type"] == "image/png"
    assert image(small).size == image(large).size == (480, 800)
    assert small.content != large.content
    assert int(large.headers["x-excerpt-pages"]) > int(small.headers["x-excerpt-pages"])


def test_live_font_size_changes_the_page_of_a_pdf(c, app, small_book, three_pages):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=small_book)
    small = c.get(url(job, "live.png?page=3&font_size=24"))
    large = c.get(url(job, "live.png?page=3&font_size=40"))
    assert small.status_code == large.status_code == 200 and small.content != large.content


def test_an_identical_live_request_renders_once(c, app, monkeypatch):
    job = make_job(app, ("book.md", TWO))
    rendered = counting(monkeypatch, "eco.web.preview.render_chapter")
    query = "live.png?format=epub&view=crosspoint&chapter=0&font_size=24&size=balanced"
    first, again = c.get(url(job, query)), c.get(url(job, query))
    assert first.content == again.content
    assert first.headers["x-excerpt-index"] == again.headers["x-excerpt-index"]
    assert first.headers["x-excerpt-pages"] == again.headers["x-excerpt-pages"]
    assert len(rendered) == 1
    for other in ("font_size=25", "size=small", "view=stock", "chapter=1"):
        c.get(url(job, query + "&" + other))  # each parameter is part of the key
    assert len(rendered) == 5


def test_the_live_answer_says_which_page_of_the_excerpt_it_shows(c, app, small_book, three_pages):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=small_book)
    r = c.get(url(job, "live.png?page=3"))
    assert (r.headers["x-excerpt-index"], r.headers["x-excerpt-pages"]) == ("0", "1")


def test_live_page_picks_the_chapter_that_holds_the_page(c, app, small_book, three_pages):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=small_book)
    one, two, three = (c.get(url(job, f"live.png?page={p}")) for p in (1, 2, 3))
    assert one.content != two.content  # chapter One, chapter Two
    assert two.content == three.content  # pages 2 and 3 are both in chapter Two
    assert body(one) == body(c.get(url(job, "preview/epub/1.png")))
    assert body(three) == body(c.get(url(job, "preview/epub/2.png")))


def test_the_live_page_of_a_page_deep_in_its_chapter_is_that_page(c, app, tmp_path, three_pages):
    # the common case of a PDF: the page asked for is not the first page of its chapter
    paragraphs = "\n\n".join(
        f"Paragraph {n} of the second chapter, with enough words to fill a few lines."
        for n in range(1, 13)
    )
    book = tmp_path / "long.book"
    book.mkdir()
    (book / "book.md").write_text(
        "<!-- page: 1 -->\n\n# One\n\nFirst chapter text.\n\n<!-- page: 2 -->\n\n# Two\n\n"
        f"{paragraphs}\n\n<!-- page: 3 -->\n\nThe text of page three.\n",
        encoding="utf-8",
    )
    job = make_job(app, ("scan.pdf", three_pages), book_dir=book)
    pages = c.get(url(job, "pages")).json()
    two = pages["chapters"][1][1]  # the first device page of chapter Two
    third = pages["page_map"].index(3) + 1  # the device page where source page 3 starts
    live = c.get(url(job, "live.png?page=3"))
    assert int(live.headers["x-excerpt-index"]) == third - two > 0
    assert int(live.headers["x-excerpt-pages"]) == len(pages["page_map"]) - two + 1
    assert body(live) == body(c.get(url(job, f"preview/epub/{third}.png")))


def test_live_chapter_shows_that_chapter(c, app):
    job = make_job(app, ("book.md", LONG))
    one = c.get(url(job, "live.png?chapter=0"))
    two = c.get(url(job, "live.png?chapter=1"))
    assert one.headers["x-excerpt-pages"] == "1"  # chapter One is one page
    assert int(two.headers["x-excerpt-pages"]) > 1  # chapter Two is not
    assert (one.headers["x-excerpt-index"], two.headers["x-excerpt-index"]) == ("0", "0")
    assert one.content != two.content


def test_live_chapter_is_laid_out_as_in_the_whole_book(c, app):
    job = make_job(app, ("book.md", LONG))
    second = c.get(url(job, "live.png?chapter=1"))
    assert second.headers["x-excerpt-index"] == "0"
    assert body(second) == body(c.get(url(job, "preview/epub/2.png")))  # chapter Two starts page 2
    first = c.get(url(job, "live.png?chapter=0"))
    assert body(first) == body(c.get(url(job, "preview/epub/1.png")))


def test_a_book_without_a_heading_is_one_chapter(c, app):
    job = make_job(app, ("book.md", b"Just text.\n\nMore text.\n"))
    assert c.get(url(job, "pages")).json()["chapters"] == []
    r = c.get(url(job, "live.png?chapter=0"))
    assert r.status_code == 200 and r.headers["x-excerpt-pages"] == "1"
    r = c.get(url(job, "live.png?chapter=1"))
    assert (r.status_code, r.json()) == (404, {"error": "No such chapter"})


def test_text_before_the_first_heading_is_not_a_chapter(c, app):
    job = make_job(app, ("book.md", b"Intro.\n\n# One\n\ntext\n\n# Two\n\nmore\n"))
    assert c.get(url(job, "pages")).json()["chapters"] == [["One", 2], ["Two", 3]]
    zero = c.get(url(job, "live.png?chapter=0"))
    one = c.get(url(job, "live.png?chapter=1"))
    assert zero.status_code == one.status_code == 200 and zero.content != one.content
    assert c.get(url(job, "live.png?chapter=2")).status_code == 404


@pytest.mark.parametrize("chapter", ["2", "99", "-1", "999999999999999999999"])
def test_a_chapter_that_does_not_exist_is_404(c, app, chapter):
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, f"live.png?chapter={chapter}"))
    assert (r.status_code, r.json()) == (404, {"error": "No such chapter"})


@pytest.mark.parametrize("page", ["4", "99", "0", "-1"])
def test_a_live_page_that_does_not_exist_is_404(c, app, small_book, three_pages, page):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=small_book)
    r = c.get(url(job, f"live.png?page={page}"))
    assert (r.status_code, r.json()) == (404, NO_PAGE)


def test_a_live_page_of_a_file_that_is_not_a_pdf_is_404(c, app):
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, "live.png?page=1"))
    assert (r.status_code, r.json()) == (404, {"error": "This file has no source pages"})


@pytest.mark.parametrize("query", ["", "page=1&chapter=0", "font_size=32"])
def test_live_takes_exactly_one_of_page_and_chapter(c, app, small_book, three_pages, query):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=small_book)
    r = c.get(url(job, "live.png?" + query))
    assert (r.status_code, r.json()) == (422, {"error": "Give exactly one of page and chapter"})


@pytest.mark.parametrize(
    "query, status, message",
    [
        ("chapter=0&font_size=15", 422, "font_size must be a whole number from 16 to 64"),
        ("chapter=0&font_size=65", 422, "font_size must be a whole number from 16 to 64"),
        ("chapter=0&font_size=-5", 422, "font_size must be a whole number from 16 to 64"),
        ("chapter=0&size=huge", 400, "Unknown size: huge"),
        ("chapter=0&view=xtc", 400, "Unknown view: xtc"),
        ("chapter=0&view=kindle", 400, "Unknown view: kindle"),
        ("chapter=0&format=xtc", 400, "Unknown format: xtc"),
    ],
)
def test_live_checks_its_values(c, app, query, status, message):
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, "live.png?" + query))
    assert (r.status_code, r.json()) == (status, {"error": message})


@pytest.mark.parametrize("query", ["chapter=x", "chapter=1.5", "page=x", "font_size=abc"])
def test_live_numbers_that_are_not_numbers_are_422(c, app, query):
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, "live.png?" + query))
    assert r.status_code == 422 and r.json()["error"].startswith(query.partition("=")[0] + ":")


def test_live_renders_with_the_requested_values_and_the_jobs_device(c, app, monkeypatch):
    options = Options(device="x3", size="best", style=PageStyle(font_size=32))
    job = make_job(app, ("book.md", TWO), options=options)
    rendered = counting(monkeypatch, "eco.web.preview.render_chapter")
    r = c.get(url(job, "live.png?chapter=1&view=crossink&font_size=40&size=small"))
    assert image(r).size == (528, 792)
    [kw] = rendered
    assert (kw["device"], kw["view"], kw["chapter"]) == ("x3", "crossink", 1)
    assert kw["source_page"] is None and kw["style"] == PageStyle(font_size=40)
    assert kw["image_profile"] == image_profile(Options(device="x3", size="small"))


def test_live_defaults_to_the_font_size_and_size_of_the_job(c, app, monkeypatch):
    options = Options(size="best", style=PageStyle(font_size=44))
    job = make_job(app, ("book.md", TWO), options=options)
    rendered = counting(monkeypatch, "eco.web.preview.render_chapter")
    c.get(url(job, "live.png?chapter=0"))
    [kw] = rendered
    assert kw["view"] == "crosspoint" and kw["style"] == PageStyle(font_size=44)
    assert kw["image_profile"] == image_profile(options)


def test_live_writes_nothing_into_the_job(c, app):
    job = make_job(app, ("book.md", TWO))
    c.get(url(job, "live.png?chapter=0"))
    assert not (app.state.store.job_dir(job.id) / "preview").exists()


def test_the_live_cache_holds_32_answers(c, app, monkeypatch):
    sizes = []

    def render(src, **kw):
        sizes.append(kw["style"].font_size)
        return Rendered([small_png(kw["style"].font_size)], [0], [], [[]]), 0

    monkeypatch.setattr("eco.web.preview.render_chapter", render)
    job = make_job(app, ("book.md", TWO))

    def live(font_size):
        r = c.get(url(job, f"live.png?chapter=0&font_size={font_size}"))
        assert r.content == small_png(font_size)  # each key has its own answer

    for font_size in range(16, 49):  # 33 different answers
        live(font_size)
    assert len(sizes) == 33
    live(48)  # the newest is there
    live(17)  # the second oldest is there: only one has gone
    assert len(sizes) == 33
    live(16)  # the oldest has gone
    assert len(sizes) == 34


def test_the_live_cache_is_kept_for_a_job_and_a_file(c, app, monkeypatch):
    calls = []

    def render(src, **kw):
        calls.append(1)
        return Rendered([small_png(1)], [0], [], [[]]), 0

    monkeypatch.setattr("eco.web.preview.render_chapter", render)
    job = make_job(app, ("a.md", TWO), ("b.md", TWO))
    other = make_job(app, ("a.md", TWO))
    for _ in range(2):
        c.get(url(job, "live.png?chapter=0", 0))
        c.get(url(job, "live.png?chapter=0", 1))
        c.get(url(other, "live.png?chapter=0", 0))
    assert len(calls) == 3


def test_the_live_cache_keeps_the_answered_page_not_the_chapter(c, app, monkeypatch):
    chapter = Rendered([small_png(1), small_png(2), small_png(3)], [0, 0, 0], [], [[], [], []])
    ref = weakref.ref(chapter)
    held = [chapter]
    monkeypatch.setattr("eco.web.preview.render_chapter", lambda src, **kw: (held[0], 2))
    job = make_job(app, ("book.md", TWO))
    r = c.get(url(job, "live.png?chapter=0"))
    assert r.content == small_png(3)
    assert (r.headers["x-excerpt-index"], r.headers["x-excerpt-pages"]) == ("2", "3")
    again = c.get(url(job, "live.png?chapter=0"))  # from the cache
    assert (again.content, again.headers["x-excerpt-index"]) == (small_png(3), "2")
    held.clear()
    del chapter
    gc.collect()
    assert ref() is None  # nothing keeps the pages of the chapter


def test_a_failed_live_render_is_not_cached(app, monkeypatch):
    calls = []

    def render(src, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("typst failed")
        return Rendered([small_png(7)], [0], [], [[]]), 0

    monkeypatch.setattr("eco.web.preview.render_chapter", render)
    job = make_job(app, ("book.md", TWO))
    quiet = TestClient(app, base_url=LOCAL, raise_server_exceptions=False)
    assert quiet.get(url(job, "live.png?chapter=0")).status_code == 500
    assert quiet.get(url(job, "live.png?chapter=0")).content == small_png(7)


# What the API shows


def test_no_json_of_the_preview_shows_a_path_of_the_server(
    c, app, tmp_path, small_book, three_pages
):
    job = make_job(app, ("scan.pdf", three_pages), book_dir=small_book)
    gone = make_job(app, ("scan.pdf", three_pages), book_dir=tmp_path / "gone.book")
    documents = [
        c.get(url(job, "pages")).json(),
        c.get(url(job, "preview/epub/99.png")).json(),
        c.get(url(job, "source/99.png")).json(),
        c.get(url(job, "pages?view=kindle")).json(),
        c.get(url(job, "live.png")).json(),
        c.get(url(job, "live.png?page=99")).json(),
        c.get(url(gone, "pages")).json(),
        c.get(url(gone, "text")).json(),
        c.get(url(job, "pages", 5)).json(),
    ]
    assert_no_path(documents, tmp_path)


def test_no_header_of_an_image_shows_a_path_of_the_server(
    c, app, tmp_path, small_book, three_pages
):
    job = make_job(app, ("a.pdf", three_pages), book_dir=small_book)
    for tail in ("source/1.png", "preview/epub/1.png", "live.png?page=1"):
        r = c.get(url(job, tail))
        assert r.status_code == 200, tail
        assert str(tmp_path) not in "".join(f"{k}{v}" for k, v in r.headers.items()), tail


# Network mode


def test_the_previews_need_the_token_and_work_with_it(tmp_path, three_pages):
    app = create_app(tmp_path, token="s3cret")
    c = TestClient(app, base_url=LOCAL)
    job = make_job(app, ("scan.pdf", three_pages), ("b.md", TWO))
    tails = [
        ("source/1.png", 0),
        ("pages", 1),
        ("preview/epub/1.png", 1),
        ("live.png?chapter=0", 1),
        ("text", 1),
    ]
    auth = {"Authorization": "Bearer s3cret"}
    for tail, n in tails:
        r = c.get(url(job, tail, n))
        assert (r.status_code, r.json()) == (401, {"error": "Missing or invalid token"}), tail
        assert c.get(url(job, tail, n), headers=auth).status_code == 200, tail


# A picture that could be a decompression bomb


@pytest.mark.filterwarnings("ignore:Image size:PIL.Image.DecompressionBombWarning")
def test_an_epub_image_over_the_pixel_limit_is_not_decoded(c, app, tmp_path, monkeypatch):
    # over the limit and under twice the limit: PIL only warns, and then decodes all of it
    width, height = 10000, 9000
    assert Image.MAX_IMAGE_PIXELS < width * height < 2 * Image.MAX_IMAGE_PIXELS
    bomb = solid_png(width, height)
    assert len(bomb) < 1_000_000  # a small file for 90 million pixels
    epub = tiny_epub(
        tmp_path,
        '<h1>Alpha</h1><p>Before.</p><p><img src="bomb.png" alt="b"/></p><p>After.</p>',
        extra={"OEBPS/bomb.png": bomb},
    )
    job = make_job(app, ("bomb.epub", epub))
    decoded = []
    real = ImageFile.ImageFile.load

    def load(self):
        decoded.append(self.size)
        return real(self)

    monkeypatch.setattr(ImageFile.ImageFile, "load", load)
    r = c.get(url(job, "pages"))
    assert r.status_code == 200 and r.json()["chapters"] == [["Alpha", 1]]
    assert c.get(url(job, "preview/epub/1.png")).status_code == 200
    assert c.get(url(job, "live.png?chapter=0")).status_code == 200
    assert (width, height) not in decoded  # the preview never held the whole picture
    assert (cache(app, job, 0, "book", "images") / "bomb.png").read_bytes() == bomb  # a copy


# The real worker


def test_a_markdown_book_made_by_the_real_worker_is_previewed(tmp_path):
    with TestClient(create_app(tmp_path, token=None), base_url=LOCAL) as c:  # with its runner
        posted = c.post("/api/jobs", files=[("files[]", ("book.md", LONG))]).json()
        base = f"/api/jobs/{posted['id']}"
        wait_for(lambda: c.get(base).json()["status"] in ("done", "failed"), 120)
        assert c.get(base).json()["status"] == "done"
        pages = c.get(f"{base}/files/0/pages").json()
        assert pages["device_pages"] > 4 and pages["chapters"] == [["One", 1], ["Two", 2]]
        r = c.get(f"{base}/files/0/preview/epub/{pages['device_pages']}.png")
        assert image(r).size == (480, 800)
        live = c.get(f"{base}/files/0/live.png?chapter=1&font_size=24")
        assert live.status_code == 200 and live.headers["x-excerpt-index"] == "0"
        assert c.get(f"{base}/files/0/text").content == LONG
        assert c.get(f"{base}/files/0/source/1.png").status_code == 404  # not a PDF
