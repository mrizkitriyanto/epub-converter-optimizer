import shutil

import pypdfium2 as pdfium
import pytest
from fixtures.make import form_image_pdf
from PIL import ImageOps
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

import eco.pdf.pages as pdf_pages
from eco.pdf.pages import (
    PdfOpenError,
    bookmarks,
    crop,
    image_bounds,
    inspect_pdf,
    pdf_metadata,
    render_page,
    to_pdfium_rect,
)

IDENTITY = "1 0 0 1 0 0"


@pytest.mark.parametrize(
    "forms",
    [
        [(IDENTITY, IDENTITY)],
        [("1 0 0 1 200 300", IDENTITY)],  # moved by the cm before the form's Do
        [("1 0 0 1 200 300", "2 0 0 2 50 100")],  # and by the form's own matrix
        [("0 1 -1 0 300 300", IDENTITY)],  # turned a quarter
        [("1 0 0 1 200 300", "2 0 0 2 50 100"), ("1 0 0 1 10 20", "1 0 0 1 5 5")],  # two deep
    ],
)
def test_an_image_inside_a_form_xobject_has_its_box_on_the_page(tmp_path, forms):
    path = form_image_pdf(tmp_path / "form.pdf", forms)
    with pdfium.PdfDocument(path) as pdf:
        (box,) = image_bounds(pdf[0])
        ink = ImageOps.invert(pdf[0].render(scale=1).to_pil().convert("L")).getbbox()
    left, top, right, bottom = ink  # pixels at scale 1 are points, top-left origin
    assert [round(v) for v in box] == [left, 792 - bottom, right, 792 - top]
    [info] = inspect_pdf(path)
    width, height = box[2] - box[0], box[3] - box[1]
    assert info.image_ratio == pytest.approx(width * height / (612 * 792))


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


# Page count and the preview picture


def blank_pdf(tmp_path, width, height):
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    path = tmp_path / f"{width}x{height}.pdf"
    with path.open("wb") as f:
        writer.write(f)
    return path


def test_page_count_does_not_read_the_pages(fixtures_dir):
    assert pdf_pages.page_count(fixtures_dir["blank"]) == 3


def test_page_count_of_a_file_that_is_not_a_pdf(tmp_path):
    junk = tmp_path / "junk.pdf"
    junk.write_text("not a pdf")
    with pytest.raises(PdfOpenError, match="Not a readable PDF: junk.pdf"):
        pdf_pages.page_count(junk)


def test_a_page_is_drawn_as_wide_as_asked(fixtures_dir):
    im = pdf_pages.render_page_fit(fixtures_dir["blank"], 1, 600, 6000)
    assert im.mode == "RGB" and im.width == 600 and abs(im.height - 600 * 792 / 612) <= 1
    assert pdf_pages.render_page_fit(fixtures_dir["blank"], 3, 300, 6000).width == 300


def test_a_page_taller_than_the_limit_is_drawn_smaller(tmp_path):
    # 600 px wide, this page would be 12,000 px tall: the scale drops until it is 6,000
    tall = pdf_pages.render_page_fit(blank_pdf(tmp_path, 400, 8000), 1, 600, 6000)
    assert tall.size == (300, 6000)
    # and a sliver of 1 pt by 14,400 pt is not asked for 8,640,000 rows, which PDFium refuses
    sliver = pdf_pages.render_page_fit(blank_pdf(tmp_path, 1, 14400), 1, 600, 6000)
    assert sliver.size == (1, 6000)


def test_a_tall_page_under_the_limit_keeps_the_width(fixtures_dir):
    assert pdf_pages.render_page_fit(fixtures_dir["tall"], 1, 600, 6000).size == (600, 3600)
