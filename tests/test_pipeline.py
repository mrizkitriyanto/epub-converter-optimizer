import hashlib
import shutil
import socket
import xml.etree.ElementTree as ET
import zipfile

import pytest
import typst
from pypdf import PdfReader, PdfWriter

from eco.book import Block
from eco.bookfolder import load_source, read_report
from eco.events import Cancelled, FindingEvent, PageEvent, StageEvent
from eco.models import ModelsMissing
from eco.options import DEVICES, Options
from eco.pdf.pages import PdfOpenError
from eco.pdf.regions import page_slices
from eco.pipeline import EXTRACTOR_VERSION, convert_file, extract_pdf, output_path

DC = "{http://purl.org/dc/elements/1.1/}"
ALL_STAGES = ("read", "layout", "fix", "epub", "optimize")
DEFAULT = Options()


def convert(path, tmp_path, options=DEFAULT, out="out", **kwargs):
    return convert_file(path, options, tmp_path / out, data_dir=tmp_path / "d", **kwargs)


def extract(pdf, data, options=DEFAULT, cancel=lambda: False, on_event=lambda e: None):
    return extract_pdf(pdf, options, data_dir=data, on_event=on_event, cancel=cancel)


def stages(events, *names):
    """(stage, status) of the stage events, for the named stages (all when none is named)."""
    return [
        (e.stage, e.status)
        for e in events
        if isinstance(e, StageEvent) and (not names or e.stage in names)
    ]


def both(*names):
    return [(name, status) for name in names for status in ("started", "finished")]


def metadata(epub):
    with zipfile.ZipFile(epub) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf = ET.fromstring(z.read(container.find(".//{*}rootfile").get("full-path")))
    return {name: opf.findtext(f".//{DC}{name}") for name in ("title", "creator", "language")}


def image_count(epub):
    """The <img> elements in the chapters. The cover page and the contents are not chapters."""
    with zipfile.ZipFile(epub) as z:
        pages = [
            n
            for n in z.namelist()
            if n.endswith(".xhtml") and not n.endswith(("cover.xhtml", "nav.xhtml"))
        ]
        return sum(z.read(n).decode().count("<img") for n in pages)


def cache_folder(pdf, data, ocr="auto"):
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return data / "cache" / f"{digest[:16]}-x{EXTRACTOR_VERSION}-{ocr}.book"


@pytest.fixture
def titled_pdf(fixtures_dir, tmp_path):
    """The blank fixture with a title, an author and one bookmark: "One", on page 1."""
    writer = PdfWriter(clone_from=PdfReader(fixtures_dir["blank"]))
    writer.add_metadata({"/Title": "A Book", "/Author": "An Author"})
    writer.add_outline_item(title="One", page_number=0)
    path = tmp_path / "titled.pdf"
    with path.open("wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def long_pdf(tmp_path):
    """70 pages of text, except page 61, which is blank."""
    source = (
        "#set page(width: 200pt, height: 200pt)\n"
        "#for n in range(1, 71) {\n"
        "  if n != 61 [Page #n]\n"
        "  if n != 70 { pagebreak() }\n"
        "}\n"
    )
    path = tmp_path / "long.pdf"
    path.write_bytes(typst.compile(source.encode(), ignore_system_fonts=True))
    return path


def test_output_never_overwrites_input(tmp_path):
    src = tmp_path / "book.x4.epub"
    src.write_bytes(b"")
    assert output_path(src, tmp_path, "x4", "epub", [src]).name == "book.x4-1.epub"


def test_output_path_is_named_after_the_input_and_skips_every_input(tmp_path):
    pdf = tmp_path / "My Book - Ü.pdf"
    assert output_path(pdf, tmp_path / "o", "x3", "epub") == tmp_path / "o" / "My Book - Ü.x3.epub"
    taken = [tmp_path / "a.x4.epub", tmp_path / "elsewhere" / ".." / "a.x4-1.epub"]
    assert output_path(tmp_path / "a.pdf", tmp_path, "x4", "epub", taken).name == "a.x4-2.epub"


def test_markdown_to_epub_events(tmp_path):
    md = tmp_path / "Bicara itu ada seninya - Ü.md"
    md.write_text("# Bab 1\n\nIsi.\n")
    seen = []
    r = convert_file(
        md, Options(device="x4"), tmp_path / "out", data_dir=tmp_path / "d", on_event=seen.append
    )
    assert r.outputs["epub"].name == "Bicara itu ada seninya - Ü.x4.epub"
    assert r.outputs["epub"].exists()
    assert [e.stage for e in seen if isinstance(e, StageEvent) and e.status == "started"] == [
        "epub",
        "optimize",
    ]


def test_no_network_during_conversion(tmp_path, monkeypatch, fixtures_dir, fake_blocks):
    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket.socket, "connect", boom)
    r = convert_file(fixtures_dir["blank"], Options(), tmp_path, data_dir=tmp_path / "d")
    assert r.outputs["epub"].exists()
    assert [f.kind for f in r.findings].count("blank_page") == 1


def test_result_describes_the_run(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("# A\n\nx\n")
    r = convert(md, tmp_path)
    assert (r.source, list(r.outputs), r.book_dir) == (md, ["epub"], None)
    assert r.sizes == {"epub": r.outputs["epub"].stat().st_size}
    assert r.seconds >= 0


def test_pdf_run_reports_stages_pages_and_findings(tmp_path, fixtures_dir, fake_blocks):
    seen = []
    r = convert(fixtures_dir["blank"], tmp_path, on_event=seen.append)
    assert stages(seen) == both(*ALL_STAGES)
    assert [e for e in seen if isinstance(e, PageEvent)] == [PageEvent(1, 2), PageEvent(2, 2)]
    assert [e.finding for e in seen if isinstance(e, FindingEvent)] == r.findings
    blank = [f for f in r.findings if f.kind == "blank_page"]
    assert [(f.page, f.level) for f in blank] == [(2, "info")]


def test_second_run_reads_the_cache(tmp_path, fixtures_dir, fake_blocks):
    pdf = fixtures_dir["blank"]
    first = convert(pdf, tmp_path, out="one")
    seen = []
    second = convert(pdf, tmp_path, out="two", on_event=seen.append)
    assert len(fake_blocks.calls) == 2  # the two chunks of the first run, none of the second
    assert first.book_dir == second.book_dir == cache_folder(pdf, tmp_path / "d")
    assert stages(seen) == both("epub", "optimize")
    assert second.findings == first.findings
    assert [e.finding for e in seen if isinstance(e, FindingEvent)] == second.findings


def test_ocr_option_has_its_own_cache_entry(tmp_path, fixtures_dir, fake_blocks):
    pdf, data = fixtures_dir["blank"], tmp_path / "d"
    auto, off = extract(pdf, data), extract(pdf, data, Options(ocr="off"))
    assert (auto, off) == (cache_folder(pdf, data), cache_folder(pdf, data, "off"))
    assert len(fake_blocks.calls) == 4
    assert extract(pdf, data, Options(ocr="off", device="x3", size="small")) == off
    assert len(fake_blocks.calls) == 4


def test_title_author_and_language_do_not_re_extract(tmp_path, fixtures_dir, fake_blocks):
    pdf = fixtures_dir["blank"]
    first = convert(pdf, tmp_path, out="one")
    second = convert(pdf, tmp_path, Options(title="New", author="Au", lang="id"), out="two")
    assert len(fake_blocks.calls) == 2
    assert metadata(first.outputs["epub"])["title"] == "blank_middle"
    assert metadata(second.outputs["epub"]) == {"title": "New", "creator": "Au", "language": "id"}
    assert load_source(second.book_dir).meta["title"] == "blank_middle"


def test_renamed_pdf_without_a_title_is_titled_after_its_new_name(
    tmp_path, fixtures_dir, fake_blocks
):
    old = tmp_path / "scan_0012.pdf"
    shutil.copy(fixtures_dir["blank"], old)
    first = convert(old, tmp_path, out="one")
    new = old.rename(tmp_path / "Atomic Habits.pdf")
    second = convert(new, tmp_path, out="two")
    given = convert(new, tmp_path, Options(title="Given"), out="three")
    assert len(fake_blocks.calls) == 2  # the renamed file read the cache
    assert second.book_dir == first.book_dir
    assert metadata(first.outputs["epub"])["title"] == "scan_0012"
    assert metadata(second.outputs["epub"])["title"] == "Atomic Habits"
    assert metadata(given.outputs["epub"])["title"] == "Given"


def test_renamed_pdf_keeps_the_title_in_its_metadata(tmp_path, titled_pdf, fake_blocks):
    first = convert(titled_pdf, tmp_path, out="one")
    second = convert(titled_pdf.rename(tmp_path / "renamed.pdf"), tmp_path, out="two")
    assert len(fake_blocks.calls) == 2
    assert metadata(first.outputs["epub"])["title"] == "A Book"
    assert metadata(second.outputs["epub"])["title"] == "A Book"


def test_options_override_the_metadata_of_markdown_and_book_folders(tmp_path, small_book):
    md = tmp_path / "x.md"
    md.write_text('---\ntitle: "Old"\nauthor: "Old Author"\n---\n\n# A\n\nText.\n')
    for source, title in ((md, "Old"), (small_book, "Small Book")):
        kept = convert(source, tmp_path, out="kept")
        assert metadata(kept.outputs["epub"])["title"] == title
        new = convert(source, tmp_path, Options(title="New", author="Au", lang="id"), out="new")
        assert metadata(new.outputs["epub"]) == {"title": "New", "creator": "Au", "language": "id"}


def test_book_folder_takes_its_metadata_from_the_pdf(tmp_path, titled_pdf, fake_blocks):
    r = convert(titled_pdf, tmp_path)
    meta = load_source(r.book_dir).meta
    assert [meta[k] for k in ("title", "author", "language", "cover")] == [
        "A Book",
        "An Author",
        "en",
        "images/cover.jpg",
    ]
    assert "titled.pdf" in meta["source"]
    assert hashlib.sha256(titled_pdf.read_bytes()).hexdigest() in meta["source"]
    assert (r.book_dir / "images" / "cover.jpg").is_file()
    assert metadata(r.outputs["epub"]) == {
        "title": "A Book",
        "creator": "An Author",
        "language": "en",
    }


def test_bookmarks_set_the_heading_levels(tmp_path, titled_pdf, fake_blocks):
    r = convert(titled_pdf, tmp_path)
    assert "\n# One\n" in (r.book_dir / "book.md").read_text()


def test_folder_left_by_an_unfinished_run_is_replaced(tmp_path, fixtures_dir, fake_blocks):
    pdf, data = fixtures_dir["blank"], tmp_path / "d"
    stale = cache_folder(pdf, data)
    (stale / "images").mkdir(parents=True)
    (stale / "images" / "old.png").write_bytes(b"old")
    assert extract(pdf, data) == stale
    assert (stale / "report.json").is_file()
    assert not (stale / "images" / "old.png").exists()


def test_page_that_never_reports_is_a_warning(tmp_path, fixtures_dir, fake_blocks):
    fake_blocks.skip = {3}
    seen = []
    r = convert(fixtures_dir["blank"], tmp_path, on_event=seen.append)
    failed = [f for f in r.findings if f.kind == "page_failed"]
    assert [(f.page, f.level) for f in failed] == [(3, "warning")]
    assert FindingEvent(failed[0]) in seen
    assert failed == [f for f in read_report(r.book_dir) if f.kind == "page_failed"]
    assert [e for e in seen if isinstance(e, PageEvent)] == [PageEvent(1, 2)]


@pytest.mark.parametrize("asked_after", [0, 1, 2])
def test_cancel_stops_at_a_chunk_boundary(tmp_path, fixtures_dir, fake_blocks, asked_after):
    data = tmp_path / "d"

    def cancel():
        return len(fake_blocks.calls) >= asked_after

    with pytest.raises(Cancelled):
        extract(fixtures_dir["blank"], data, cancel=cancel)
    assert len(fake_blocks.calls) == asked_after  # the blank fixture has two chunks
    assert not list(data.glob("cache/*/report.json"))


def test_cancelled_conversion_writes_no_output(tmp_path, fixtures_dir, fake_blocks):
    with pytest.raises(Cancelled):
        convert(fixtures_dir["blank"], tmp_path, cancel=lambda: True)
    assert not (tmp_path / "out").exists()


def test_layout_runs_in_chunks_of_contiguous_non_blank_pages(tmp_path, long_pdf, fake_blocks):
    seen = []
    extract(long_pdf, tmp_path / "d", on_event=seen.append)
    assert [(c.first, c.last) for c in fake_blocks.calls] == [(1, 50), (51, 60), (62, 70)]
    assert {c.models for c in fake_blocks.calls} == {tmp_path / "d" / "models"}
    assert [e for e in seen if isinstance(e, PageEvent)][-1] == PageEvent(69, 69)


def test_scanned_pages_get_an_ocr_finding_unless_ocr_is_off(tmp_path, fixtures_dir, fake_blocks):
    pdf = fixtures_dir["scanned"][0]
    fake_blocks.blocks = [Block("paragraph", "Scanned page with no text layer.", page=1)]
    on = convert(pdf, tmp_path, out="on")
    off = convert(pdf, tmp_path, Options(ocr="off"), out="off")
    assert [f.page for f in on.findings if f.kind == "ocr_page"] == [1]
    assert not [f for f in off.findings if f.kind == "ocr_page"]
    assert [(c.ocr, c.scanned) for c in fake_blocks.calls] == [
        ("auto", frozenset({1})),
        ("off", frozenset({1})),
    ]


def test_word_hyphenated_across_a_page_break_is_joined(tmp_path, fixtures_dir, fake_blocks):
    fake_blocks.blocks = [
        Block("paragraph", "Kata itu terlihat seper–", page=1),
        Block("paragraph", "tinya benar. Kata sepertinya muncul lagi di sini.", page=3),
    ]
    r = convert(fixtures_dir["blank"], tmp_path)
    text = (r.book_dir / "book.md").read_text()
    assert "Kata itu terlihat sepertinya benar. Kata sepertinya muncul lagi di sini." in text


def test_text_is_normalised_but_code_keeps_its_indentation(tmp_path, fixtures_dir, fake_blocks):
    code = "def f():\n    return 1"
    fake_blocks.blocks = [
        Block("paragraph", "The \N{LATIN SMALL LIGATURE FI}rst  line.", page=1),
        Block("code", code, page=3),
    ]
    r = convert(fixtures_dir["blank"], tmp_path)
    text = (r.book_dir / "book.md").read_text()
    assert "The first line." in text
    assert f"```\n{code}\n```" in text


def test_heading_clean_up_uses_the_language_found_in_the_book(tmp_path, fixtures_dir, fake_blocks):
    fake_blocks.blocks = [
        Block("paragraph", "Buku ini ditulis untuk dia dan dengan cara yang itu.", page=1),
        Block("heading", "Pergi ke Kelas", page=1, ocr=True),
        Block("heading", "Seni iMendengar r Aktif", page=3, ocr=True),
        Block("heading", "Seni iMendengar r Aktif", page=3),
    ]
    r = convert(fixtures_dir["blank"], tmp_path)
    text = (r.book_dir / "book.md").read_text()
    assert load_source(r.book_dir).meta["language"] == "id"
    assert "Pergi ke Kelas" in text  # "ke" is a word of the language, not an OCR artifact
    assert text.count("Seni Mendengar Aktif") == 1  # the OCR heading is cleaned
    assert text.count("Seni iMendengar r Aktif") == 1  # the heading from a text layer is not


@pytest.mark.parametrize(("device", "landscape"), [("x4", False), ("x3", False), ("x4", True)])
def test_pages_mode_cuts_slices_for_the_device_screen(tmp_path, fixtures_dir, device, landscape):
    pdf = fixtures_dir["tall"]
    r = convert(pdf, tmp_path, Options(device=device, mode="pages", landscape=landscape))
    slices = len(page_slices(pdf, 1, DEVICES[device], landscape))
    assert slices > 1
    assert image_count(r.outputs["epub"]) == slices


def test_pages_mode_on_general_keeps_every_page_whole(tmp_path, fixtures_dir):
    r = convert(fixtures_dir["tall"], tmp_path, Options(device="general", mode="pages"))
    assert image_count(r.outputs["epub"]) == 1


def test_pages_mode_skips_blank_pages_and_needs_no_models_or_cache(tmp_path, fixtures_dir):
    seen = []
    r = convert(fixtures_dir["blank"], tmp_path, Options(mode="pages"), on_event=seen.append)
    assert image_count(r.outputs["epub"]) == 2
    assert [f.page for f in r.findings if f.kind == "blank_page"] == [2]
    assert stages(seen) == both("read", "layout", "epub", "optimize")
    assert [e for e in seen if isinstance(e, PageEvent)] == [PageEvent(1, 2), PageEvent(2, 2)]
    assert r.book_dir is None
    assert not (tmp_path / "d" / "cache").exists()


def test_epub_input_is_only_optimised(tmp_path, messy_epub):
    seen = []
    r = convert(messy_epub, tmp_path, on_event=seen.append)
    assert stages(seen) == both("optimize")
    assert r.outputs["epub"] == tmp_path / "out" / "messy.x4.epub"
    assert r.book_dir is None
    assert r.findings
    assert [e.finding for e in seen if isinstance(e, FindingEvent)] == r.findings


def test_converting_an_output_again_keeps_the_input(tmp_path, messy_epub):
    again = messy_epub.with_name("book.x4.epub")
    messy_epub.rename(again)
    before = again.read_bytes()
    r = convert_file(again, Options(device="x4"), tmp_path, data_dir=tmp_path / "d")
    assert r.outputs["epub"].name == "book.x4-1.epub"
    assert again.read_bytes() == before


def test_book_folder_goes_to_epub_and_optimize(tmp_path, small_book):
    seen = []
    r = convert(small_book, tmp_path, on_event=seen.append)
    assert stages(seen) == both("epub", "optimize")
    assert (r.book_dir, r.outputs["epub"].name) == (small_book, "small.x4.epub")


def test_unreadable_pdf_fails_first(tmp_path, fake_blocks):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    seen = []
    with pytest.raises(PdfOpenError, match="Not a readable PDF: broken.pdf"):
        convert(broken, tmp_path, on_event=seen.append)
    assert fake_blocks.calls == []
    assert stages(seen) == [("read", "started")]


@pytest.mark.parametrize("mode", ["auto", "pages"])
def test_missing_pdf_is_not_readable(tmp_path, fake_blocks, mode):
    with pytest.raises(PdfOpenError, match="Not a readable PDF: gone.pdf"):
        convert(tmp_path / "gone.pdf", tmp_path, Options(mode=mode))
    assert fake_blocks.calls == []


def test_password_protected_pdf_fails_first(tmp_path, encrypted_pdf, fake_blocks):
    with pytest.raises(PdfOpenError, match="PDF is password-protected: locked.pdf"):
        convert(encrypted_pdf, tmp_path)
    assert fake_blocks.calls == []


def test_missing_models_stop_the_conversion(tmp_path, fixtures_dir):
    seen = []
    with pytest.raises(ModelsMissing):
        convert(fixtures_dir["blank"], tmp_path, on_event=seen.append)
    assert stages(seen) == [*both("read"), ("layout", "started")]
    assert not list((tmp_path / "d").glob("cache/*/report.json"))


def test_unsupported_input(tmp_path):
    note = tmp_path / "notes.txt"
    note.write_text("x")
    with pytest.raises(ValueError, match="Unsupported input: notes.txt"):
        convert(note, tmp_path)


def test_a_cached_folder_whose_book_md_is_gone_is_extracted_again(
    tmp_path, fixtures_dir, fake_blocks
):
    """A virus scanner can remove book.md after report.json marked the folder complete."""
    pdf, data = fixtures_dir["blank"], tmp_path / "d"
    folder = extract(pdf, data)
    (folder / "book.md").unlink()
    assert extract(pdf, data) == folder
    assert (folder / "book.md").is_file()
    assert len(fake_blocks.calls) == 4  # two chunks each time
