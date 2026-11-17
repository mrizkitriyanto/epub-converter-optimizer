import shutil

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from eco.pdf.pages import (
    PdfOpenError,
    bookmarks,
    crop,
    inspect_pdf,
    pdf_metadata,
    render_page,
    to_pdfium_rect,
)


def test_inspect(fixtures_dir):
    pages = inspect_pdf(fixtures_dir["blank"])
    assert [p.number for p in pages] == [1, 2, 3]
    assert [p.is_blank for p in pages] == [False, True, False]
    assert inspect_pdf(fixtures_dir["scanned"][0])[0].is_scanned


def test_text_page_is_not_scanned(fixtures_dir):
    page = inspect_pdf(fixtures_dir["two_column"][0])[0]
    assert page.chars > 50
    assert not page.is_scanned
    assert 0 <= page.image_ratio <= 1


def test_pdfium_rect_respects_cropbox(fixtures_dir):
    info = inspect_pdf(fixtures_dir["code"][0])[0]
    assert (info.crop_x, info.crop_y) == (54.0, 63.0)
    l, b, r, t = to_pdfium_rect(info, (10.0, 20.0, 110.0, 70.0))
    assert (l, r, t, b) == (64.0, 164.0, 63.0 + info.height - 20.0, 63.0 + info.height - 70.0)


def test_password_pdf_message(encrypted_pdf):
    with pytest.raises(PdfOpenError, match="PDF is password-protected: locked.pdf"):
        inspect_pdf(encrypted_pdf)


@pytest.mark.parametrize("call", [inspect_pdf, bookmarks, pdf_metadata])
def test_not_a_pdf_message(tmp_path, call):
    junk = tmp_path / "junk.pdf"
    junk.write_text("not a pdf")
    with pytest.raises(PdfOpenError, match="Not a readable PDF: junk.pdf"):
        call(junk)


def test_missing_file_message(tmp_path):
    with pytest.raises(PdfOpenError, match="Not a readable PDF: gone.pdf"):
        inspect_pdf(tmp_path / "gone.pdf")


def test_render_page_size_and_grayscale(fixtures_dir):
    path = fixtures_dir["blank"]
    info = inspect_pdf(path)[0]
    color = render_page(path, 1, scale=1.0)
    assert color.mode == "RGB"
    assert color.size == (round(info.width), round(info.height))
    assert render_page(path, 1, scale=1.0, grayscale=True).mode == "L"
    assert render_page(path, 1, scale=2.0).width == 2 * color.width


def test_crop_follows_the_padded_box(fixtures_dir):
    path, _, bbox = fixtures_dir["code"]
    x0, y0, x1, y1 = bbox
    im = crop(path, 1, bbox, scale=3.0, pad=4.0)
    assert im.mode == "L"
    assert im.size == (round((x1 - x0 + 8) * 3), round((y1 - y0 + 8) * 3))
    assert im.getextrema()[0] < 128  # the code text is dark, not a black out-of-page fill


def test_crop_at_the_page_edge_has_no_black_bars(fixtures_dir):
    path = fixtures_dir["blank"]
    info = inspect_pdf(path)[0]
    im = crop(path, 2, (0.0, 0.0, info.width, info.height), scale=1.0, pad=10.0)
    assert im.size == (round(info.width), round(info.height))
    assert im.getextrema() == (255, 255)


def test_name_with_space_and_non_ascii(fixtures_dir, tmp_path):
    path = tmp_path / "Ü test.pdf"
    shutil.copy(fixtures_dir["blank"], path)
    assert len(inspect_pdf(path)) == 3
    assert render_page(path, 1, scale=1.0).width > 0


def test_images_outlive_the_document(fixtures_dir):
    im = render_page(fixtures_dir["blank"], 1, scale=1.0)
    im.load()
    assert im.getextrema()


@pytest.fixture
def titled_pdf(fixtures_dir, tmp_path):
    writer = PdfWriter(clone_from=PdfReader(fixtures_dir["blank"]))
    writer.add_metadata({"/Title": "  A Book  ", "/Author": "   "})
    top = writer.add_outline_item(title="Part", page_number=0)
    writer.add_outline_item(title="Chapter", page_number=2, parent=top)
    no_dest = DictionaryObject({NameObject("/Title"): TextStringObject("No destination")})
    writer.add_outline_item_dict(no_dest)
    path = tmp_path / "titled.pdf"
    with path.open("wb") as f:
        writer.write(f)
    return path


def test_bookmarks(titled_pdf):
    got = [(b.title, b.level, b.page) for b in bookmarks(titled_pdf)]
    assert got == [("Part", 0, 1), ("Chapter", 1, 3)]


def test_bookmarks_empty(fixtures_dir):
    assert bookmarks(fixtures_dir["blank"]) == []


def test_metadata_is_stripped_and_empty_dropped(titled_pdf):
    assert pdf_metadata(titled_pdf) == {"title": "A Book"}
