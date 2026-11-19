from itertools import pairwise

import pytest
import typst
from fixtures.make import form_image_pdf
from PIL import Image, ImageChops

from eco.book import Block
from eco.events import Finding
from eco.pdf.pages import PageInfo, inspect_pdf
from eco.pdf.regions import (
    keep_picture_text_as_images,
    leave_out_the_cover_page,
    materialize_regions,
    page_slices,
    render_cover,
)

SCREEN = (480, 800)


def _pages(path):
    return {info.number: info for info in inspect_pdf(path)}


def test_formula_becomes_image(fixtures_dir, tmp_path):
    path, bbox = fixtures_dir["formula"]
    block = Block("formula", text="y = F(x)", page=1, bbox=bbox)
    images = tmp_path / "images"
    blocks, findings = materialize_regions(path, [block], _pages(path), images)
    assert [(b.kind, b.text, b.image) for b in blocks] == [
        ("image", "formula", "images/p0001-formula-1.png")
    ]
    assert findings == [Finding(1, "formula_as_image", "info", "Formula kept as an image.")]
    with Image.open(images / "p0001-formula-1.png") as im:
        assert im.format == "PNG"
        assert abs(im.width - round(3 * (bbox[2] - bbox[0] + 8))) <= 2
        assert im.mode == "L"
    assert block.kind == "formula"


def test_photo_picture_is_saved_as_colour_jpeg(fixtures_dir, tmp_path):
    path, bbox = fixtures_dir["photo"]
    block = Block("picture", text="alt", caption="Figure 1", page=1, bbox=bbox)
    blocks, findings = materialize_regions(path, [block], _pages(path), tmp_path / "images")
    assert findings == []
    assert (blocks[0].kind, blocks[0].text, blocks[0].caption) == ("image", "alt", "Figure 1")
    assert blocks[0].image == "images/p0001-picture-1.jpg"
    with Image.open(tmp_path / blocks[0].image) as im:
        assert im.format == "JPEG"
        assert im.mode == "RGB"
        assert "progressive" not in im.info
        r, g, _ = im.split()
        assert ImageChops.difference(r, g).getbbox() is not None


def test_line_art_picture_is_saved_as_colour_png(fixtures_dir, tmp_path):
    path, bbox = fixtures_dir["shapes"]
    block = Block("picture", page=1, bbox=bbox)
    blocks, _ = materialize_regions(path, [block], _pages(path), tmp_path / "images")
    assert blocks[0].image == "images/p0001-picture-1.png"
    with Image.open(tmp_path / blocks[0].image) as im:
        assert im.format == "PNG"
        assert im.convert("RGB").getpixel((im.width // 6, im.height // 2)) == (255, 0, 0)


def test_table_keeps_html_and_gets_twin(fixtures_dir, tmp_path):
    path, bbox = fixtures_dir["shapes"]
    block = Block("table", html="<table></table>", page=1, bbox=bbox)
    blocks, findings = materialize_regions(path, [block], _pages(path), tmp_path / "images")
    assert (blocks[0].kind, blocks[0].html) == ("table", "<table></table>")
    assert blocks[0].image == "images/p0001-table-1.png"
    assert findings == []
    with Image.open(tmp_path / blocks[0].image) as im:
        assert im.format == "PNG"
        assert im.mode == "RGB"
        assert im.convert("RGB").getpixel((im.width // 6, im.height // 2)) == (255, 0, 0)


def test_numbering_is_per_page_and_kind(fixtures_dir, tmp_path):
    path, bbox = fixtures_dir["shapes"]
    blocks = [Block("picture", page=1, bbox=bbox), Block("picture", page=1, bbox=bbox)]
    blocks.append(Block("table", page=1, bbox=bbox))
    done, _ = materialize_regions(path, blocks, _pages(path), tmp_path / "images")
    assert [b.image for b in done] == [
        "images/p0001-picture-1.png",
        "images/p0001-picture-2.png",
        "images/p0001-table-1.png",
    ]


def test_blocks_without_bbox_or_page_info_pass_through(fixtures_dir, tmp_path):
    path, bbox = fixtures_dir["shapes"]
    blocks = [
        Block("picture", text="no box", page=1),
        Block("paragraph", text="text", page=1, bbox=bbox),
        Block("picture", page=7, bbox=bbox),
    ]
    done, findings = materialize_regions(path, blocks, _pages(path), tmp_path / "images")
    assert done == blocks
    assert findings == []
    assert not (tmp_path / "images").exists() or not list((tmp_path / "images").iterdir())


def _page_blocks(bbox):
    return [
        Block("heading", "Title", level=1, page=1),
        Block("picture", page=1, bbox=bbox),
        Block("paragraph", "After.", page=1),
        Block("paragraph", "Next page.", page=2),
    ]


def test_picture_page_becomes_one_page_image(fixtures_dir, tmp_path):
    path, _ = fixtures_dir["photo"]
    pages = _pages(path)
    info = pages[1]
    blocks = _page_blocks((0.0, 0.0, info.width, info.height * 0.81))
    done, findings = materialize_regions(path, blocks, pages, tmp_path / "images")
    assert [(b.kind, b.text, b.page, b.image) for b in done[:2]] == [
        ("image", "Page 1", 1, "images/p0001-page.jpg"),
        ("paragraph", "Next page.", 2, ""),
    ]
    assert len(done) == 2
    assert findings == [Finding(1, "page_as_image", "info", "Picture page kept as one image.")]
    with Image.open(tmp_path / "images" / "p0001-page.jpg") as im:
        assert im.format == "JPEG"
        assert abs(im.width - round(3 * info.width)) <= 1


def test_page_under_80_percent_picture_is_not_replaced(fixtures_dir, tmp_path):
    path, _ = fixtures_dir["photo"]
    pages = _pages(path)
    info = pages[1]
    blocks = _page_blocks((0.0, 0.0, info.width, info.height * 0.79))
    done, findings = materialize_regions(path, blocks, pages, tmp_path / "images")
    assert [b.kind for b in done] == ["heading", "image", "paragraph", "paragraph"]
    assert findings == []


def test_picture_area_is_clipped_to_the_page(fixtures_dir, tmp_path):
    path, _ = fixtures_dir["photo"]
    pages = _pages(path)
    info = pages[1]
    blocks = _page_blocks((-500.0, -500.0, info.width * 0.5, info.height * 0.5))
    done, findings = materialize_regions(path, blocks, pages, tmp_path / "images")
    assert findings == []
    assert len(done) == 4


def test_text_page_with_big_picture_is_not_replaced(fixtures_dir, tmp_path):
    path = fixtures_dir["two_column"][0]
    pages = _pages(path)
    assert pages[1].chars >= 200
    info = pages[1]
    block = Block("picture", page=1, bbox=(0.0, 0.0, info.width, info.height))
    done, findings = materialize_regions(path, [block], pages, tmp_path / "images")
    assert done[0].image.startswith("images/p0001-picture-1.")
    assert findings == []


def test_render_cover(fixtures_dir, tmp_path):
    path, _ = fixtures_dir["photo"]
    images = tmp_path / "images"
    assert render_cover(path, images) == "images/cover.jpg"
    with Image.open(images / "cover.jpg") as im:
        assert im.format == "JPEG"
        assert im.mode == "RGB"
        assert "progressive" not in im.info
        assert im.size == (1224, 1584)


def test_page_slices_fit_the_screen_and_overlap(fixtures_dir):
    slices = page_slices(fixtures_dir["tall"], 1, SCREEN)
    assert len(slices) > 2
    assert all(s.width <= 480 and s.height <= 800 for s in slices)
    assert all(s.height == 800 for s in slices[:-1])
    for upper, lower in pairwise(slices):
        assert upper.crop((0, 760, upper.width, 800)).tobytes() == (
            lower.crop((0, 0, lower.width, 40)).tobytes()
        )


def test_page_slices_landscape_are_rotated_to_portrait(fixtures_dir):
    upright = page_slices(fixtures_dir["tall"], 1, SCREEN)
    landscape = page_slices(fixtures_dir["tall"], 1, SCREEN, landscape=True)
    assert len(landscape) > len(upright)
    assert all(s.width <= 480 and s.height <= 800 for s in landscape)
    assert all(s.width == 480 for s in landscape[:-1])


def test_landscape_slice_is_rotated_clockwise(tmp_path):
    source = "#set page(width: 240pt, height: 160pt, margin: 0pt)\n"
    source += '#place(top + left, rect(width: 40pt, height: 40pt, fill: rgb("#ff0000")))\n'
    source += '#place(bottom + right, rect(width: 40pt, height: 40pt, fill: rgb("#0000ff")))\n'
    path = tmp_path / "corners.pdf"
    path.write_bytes(typst.compile(source.encode(), ignore_system_fonts=True))
    (only,) = page_slices(path, 1, SCREEN, landscape=True)
    assert only.size == (480, 720)
    assert only.getpixel((479, 0)) == (255, 0, 0)
    assert only.getpixel((0, 719)) == (0, 0, 255)


def test_page_slices_do_not_scale_up(tmp_path):
    source = "#set page(width: 200pt, height: 300pt, margin: 0pt)\n"
    source += (
        "#place(top + left, dx: 50pt, dy: 50pt, rect(width: 100pt, height: 200pt, fill: black))"
    )
    path = tmp_path / "small.pdf"
    path.write_bytes(typst.compile(source.encode(), ignore_system_fonts=True))
    (only,) = page_slices(path, 1, SCREEN)
    assert only.size == (300, 600)


def test_blank_page_has_no_slices(fixtures_dir):
    assert page_slices(fixtures_dir["blank"], 2, SCREEN) == []


def picture_text_blocks():
    return [
        Block(
            "paragraph", "Ordinary text that the text layer holds.", page=1, bbox=(72, 60, 300, 72)
        ),
        Block("heading", "Pictured words", page=1, bbox=(108, 158, 250, 172)),  # OCR, picture 1
        Block(
            "table",
            html="<table><tr><td>inside a figure</td></tr></table>",
            page=1,
            bbox=(108, 190, 290, 240),
        ),  # OCR, picture 1
        Block(
            "paragraph", "Figure 1 - a caption in the text layer", page=1, bbox=(100, 260, 330, 272)
        ),
        Block(
            "paragraph", "Overlay label", page=1, bbox=(110, 330, 190, 342)
        ),  # text layer, picture 2
        Block("paragraph", "Words nowhere at all", page=1, bbox=(72, 500, 300, 512)),  # no picture
    ]


def test_text_read_from_a_picture_on_a_text_layer_page_becomes_the_picture(fixtures_dir):
    pdf = fixtures_dir["picture_text"]
    pages = {info.number: info for info in inspect_pdf(pdf)}
    blocks = picture_text_blocks()
    out, findings = keep_picture_text_as_images(pdf, blocks, pages, "auto")
    assert [b.kind for b in out] == ["paragraph", "picture", "paragraph", "paragraph", "paragraph"]
    picture = out[1]
    assert picture.page == 1 and picture.text == ""
    assert [round(v) for v in picture.bbox] == [100, 150, 300, 250]  # the whole picture
    assert out[2:] == blocks[3:]
    assert [(f.page, f.kind, f.level) for f in findings] == [(1, "picture_text_as_image", "info")]


PICTURE_1 = [100, 150, 300, 250]


@pytest.mark.parametrize(
    "docling, kept",
    [
        # a logo Docling found inside the picture: the whole picture replaces it, with its caption
        (
            Block("picture", page=1, bbox=(260, 215, 290, 245), caption="Logo"),
            [("picture", PICTURE_1, "Logo")],
        ),
        # Docling's picture covers most of it: it stays, grown to the whole picture
        (Block("picture", page=1, bbox=(104, 152, 300, 250)), [("picture", PICTURE_1, "")]),
    ],
)
def test_the_whole_picture_is_kept_whatever_picture_docling_found_in_it(
    fixtures_dir, docling, kept
):
    pdf = fixtures_dir["picture_text"]
    pages = {info.number: info for info in inspect_pdf(pdf)}
    blocks = picture_text_blocks()
    blocks.insert(3, docling)
    out, findings = keep_picture_text_as_images(pdf, blocks, pages, "auto")
    pictures = [(b.kind, [round(v) for v in b.bbox], b.caption) for b in out if b.kind == "picture"]
    assert pictures == kept
    assert [b.text for b in out if b.kind != "picture"] == [
        "Ordinary text that the text layer holds.",
        "Figure 1 - a caption in the text layer",
        "Overlay label",
        "Words nowhere at all",
    ]
    assert [(f.page, f.kind) for f in findings] == [(1, "picture_text_as_image")]


def test_a_block_that_holds_text_layer_words_outside_the_picture_keeps_its_text(fixtures_dir):
    pdf = fixtures_dir["picture_text"]
    pages = {info.number: info for info in inspect_pdf(pdf)}
    # its centre is in picture 1 and most of its words are OCR, but it reaches down over the
    # caption, which is in the text layer
    block = Block(
        "paragraph",
        "Pictured words inside a figure zzz yyy Figure",
        page=1,
        bbox=(100, 150, 330, 272),
    )
    assert keep_picture_text_as_images(pdf, [block], pages, "auto") == ([block], [])


def test_a_picture_inside_a_form_xobject_is_found_where_it_is_drawn(tmp_path):
    # drawn at (200, 300)-(300, 350) in PDF space: (200, 442)-(300, 492) from the top left
    pdf = form_image_pdf(tmp_path / "form.pdf", [("1 0 0 1 200 300", "1 0 0 1 0 0")])
    block = Block("paragraph", "Read from the picture", page=1, bbox=(205, 445, 295, 490))
    out, findings = keep_picture_text_as_images(pdf, [block], _pages(pdf), "auto")
    assert [(b.kind, [round(v) for v in b.bbox]) for b in out] == [
        ("picture", [200, 442, 300, 492])
    ]
    assert [f.kind for f in findings] == ["picture_text_as_image"]


def test_ocr_force_and_ocr_off_keep_the_text(fixtures_dir):
    pdf = fixtures_dir["picture_text"]
    pages = {info.number: info for info in inspect_pdf(pdf)}
    for ocr in ("force", "off"):
        assert keep_picture_text_as_images(pdf, picture_text_blocks(), pages, ocr) == (
            picture_text_blocks(),
            [],
        )


def test_a_scanned_page_keeps_its_ocr_text(fixtures_dir):
    scan = PageInfo(1, 612.0, 792.0, 0.0, 0.0, 0, 1.0)
    blocks = picture_text_blocks()
    assert keep_picture_text_as_images(fixtures_dir["picture_text"], blocks, {1: scan}, "auto") == (
        blocks,
        [],
    )


def info(number, scanned):
    """A page with a text layer, or a scanned one (a picture and no text)."""
    return PageInfo(number, 612.0, 792.0, 0.0, 0.0, 0 if scanned else 900, 1.0 if scanned else 0.0)


def cover_blocks():
    return [
        Block("heading", "A Cover Title", page=1),
        Block("picture", page=1, bbox=(0.0, 0.0, 612.0, 792.0)),
        Block("paragraph", "Body text.", page=2),
    ]


def test_a_picture_page_1_of_a_digital_book_is_only_the_cover():
    out, findings = leave_out_the_cover_page(cover_blocks(), {1: info(1, True), 2: info(2, False)})
    assert out == cover_blocks()[2:]
    assert [(f.page, f.kind, f.level) for f in findings] == [(1, "cover_page", "info")]


@pytest.mark.parametrize(
    "pages",
    [
        {1: info(1, True), 2: info(2, True)},  # a scanned book: page 1 can be content
        {1: info(1, False), 2: info(2, False)},  # a title page with a text layer keeps its text
    ],
)
def test_other_first_pages_stay(pages):
    assert leave_out_the_cover_page(cover_blocks(), pages) == (cover_blocks(), [])
