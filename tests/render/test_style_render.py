"""The renderer honours every setting of the page style (spec 8.18, 9 item 15), one test each, and
reports where the images are. A test looks at the pixels of a page or at the text a PDF of the same
source holds, never at the Typst source alone."""

import json
import math
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
import typst
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader

import eco.render.pages as pages_module
from eco.bookfolder import load_source
from eco.options import Options, image_profile
from eco.render.md2typst import to_typst
from eco.render.pages import render_book, render_chapter
from eco.style import FONTS_DIR, PageStyle, font_dirs

FAMILIES = ("Literata", "Bitter", "Lexend Deca", "Libertinus Serif")
SHORT = "# One\n\nShort chapter text.\n"
# Chapters of one page, three of them: the bar's numbers are then easy to read.
THREE = "# A\n\ntext\n\n# B\n\ntext\n\n# C\n\ntext\n"
LONG = "\n\n".join(
    f"Paragraph {n} of a chapter, with enough words to fill a few lines." for n in range(1, 31)
)
FILLER = "The quick brown fox jumps over the lazy dog and keeps on running. " * 30
QUIET = {"bar_page": False, "bar_chapter_title": False}  # a bar that has no text
OVERHANG = 10  # px that a glyph may reach past the line it is in, at a text size of 32


def book(tmp_path, markdown, name="b.md"):
    md = tmp_path / name
    md.write_text(markdown, encoding="utf-8")
    return load_source(md)


def render(src, style=None, *, device="x4", view="xtc", **kw):
    return render_book(src, device=device, style=style or PageStyle(), view=view, **kw)


def page(rendered, n=0) -> Image.Image:
    return Image.open(BytesIO(rendered.pages[n]))


def ink(im: Image.Image, box) -> tuple | None:
    """The bounding box of the pixels in `box` that are not white (relative to `im`), or None."""
    left, top, *_ = box
    found = ImageChops.invert(im.crop(box)).getbbox()
    return (
        None
        if found is None
        else (found[0] + left, found[1] + top, found[2] + left, found[3] + top)
    )


def pdf_pages(src, style, tmp_path) -> tuple[list[str], set[str]]:
    """The text of each page and the names of the fonts of a PDF of the same Typst source."""
    folder = tmp_path / "pdf"
    folder.mkdir(exist_ok=True)
    for name, data in to_typst(src, device="x4", style=style, view="xtc").items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.read_bytes() if isinstance(data, Path) else data)
    pdf = typst.compile(
        folder / "main.typ",
        root=str(folder),
        format="pdf",
        ignore_system_fonts=True,
        font_paths=[str(d) for d in font_dirs()],
    )
    reader = PdfReader(BytesIO(pdf))
    fonts = {
        str(font.get_object()["/BaseFont"])
        for p in reader.pages
        for font in p["/Resources"]["/Font"].values()
    }
    return [p.extract_text() for p in reader.pages], fonts


# Text


def test_each_font_looks_different(tmp_path):
    src = book(tmp_path, SHORT)
    pages = {family: render(src, PageStyle(font=family)).pages[0] for family in FAMILIES}
    assert len(set(pages.values())) == 4  # none of them fell back to another


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("weight, name", [(400, "Regular"), (700, "Bold")])
def test_the_text_is_set_in_the_family_and_weight_of_the_style(tmp_path, family, weight, name):
    src = book(tmp_path, "Plain words only.\n")
    _, fonts = pdf_pages(src, PageStyle(font=family, font_weight=weight), tmp_path)
    assert fonts and {f.partition("+")[2] for f in fonts} <= {
        f"{family.replace(' ', '')}-{name}",
        f"{family.replace(' ', '')}-{name}-Identity-H",  # how Typst names its own font
    }


def test_a_heavier_weight_is_darker(tmp_path):
    src = book(tmp_path, SHORT)
    mean = {
        weight: ImageStat.Stat(page(render(src, PageStyle(font_weight=weight)))).mean[0]
        for weight in (400, 500, 600, 700, 800)
    }
    assert mean[800] < mean[700] < mean[600] < mean[500] < mean[400]


def test_the_size_of_the_text_follows_the_style(tmp_path):
    src = book(tmp_path, LONG)
    counts = [len(render(src, PageStyle(font_size=size)).pages) for size in (20, 32, 48)]
    assert counts[0] < counts[1] < counts[2]


def test_taller_lines_make_more_pages(tmp_path):
    src = book(tmp_path, LONG)
    tight = render(src, PageStyle(line_height=120))
    loose = render(src, PageStyle(line_height=200))
    assert len(loose.pages) > len(tight.pages)


def test_the_margin_keeps_the_text_inside_it(tmp_path):
    src = book(tmp_path, FILLER)
    im = page(render(src, PageStyle(margin=40, bar_position="off")))
    assert ink(im, (0, 0, 40, 800)) is None  # the left 40 px columns are white
    _, top, right, bottom = ImageChops.invert(im).getbbox()
    # A glyph reaches past its line by a few px (an f at the end of a line, a descender below the
    # last one), so the other three sides get that much.
    assert top >= 40 - OVERHANG and right <= 480 - 40 + OVERHANG and bottom <= 800 - 40 + OVERHANG
    assert right > 480 - 40 - 20 and bottom > 800 - 40 - 20  # and the text does fill the page
    tight = ImageChops.invert(page(render(src, PageStyle(margin=0, bar_position="off")))).getbbox()
    assert tight[0] < 4  # with no margin it starts at the edge


def test_the_margin_keeps_the_body_white_next_to_a_bar(tmp_path):
    im = page(render(book(tmp_path, FILLER), PageStyle(margin=40)))
    body = (0, 0, 40, 800 - 40 - 22)  # the bar has its own side margin
    assert ink(im, body) is None


def test_left_alignment_changes_the_page(tmp_path):
    src = book(tmp_path, FILLER)
    justified = render(src, PageStyle(align="justify")).pages[0]
    left = render(src, PageStyle(align="left")).pages[0]
    assert justified != left

    def flush_rows(png):  # rows whose text ends at the right margin
        im = Image.open(BytesIO(png))
        return sum(ink(im, (460, y, 464, y + 1)) is not None for y in range(740))

    assert flush_rows(justified) > flush_rows(left)


def test_hyphenation_can_be_turned_off(tmp_path):
    src = book(
        tmp_path,
        "---\nlanguage: en\n---\n" + "Extraordinarily unconventional telecommunications. " * 12,
    )
    on = PageStyle(hyphenate=True, bar_position="off")
    off = replace(on, hyphenate=False)
    assert render(src, on).pages[0] != render(src, off).pages[0]
    soft_hyphen = "\xad"
    assert soft_hyphen in "".join(pdf_pages(src, on, tmp_path)[0])
    assert soft_hyphen not in "".join(pdf_pages(src, off, tmp_path)[0])


def test_focus_keeps_hyphenation(tmp_path):
    src = book(
        tmp_path,
        "---\nlanguage: en\n---\n" + "Extraordinarily unconventional telecommunications. " * 12,
    )
    style = PageStyle(hyphenate=True, focus_mode=True, bar_position="off")
    assert "\xad" in "".join(pdf_pages(src, style, tmp_path)[0])


def test_the_language_of_the_style_wins_over_the_book(tmp_path):
    german = "Donaudampfschifffahrtsgesellschaft " * 8
    src = book(tmp_path, f"---\nlanguage: en\n---\n{german}\n")
    auto = render(src, PageStyle(font_size=40, bar_position="off")).pages[0]
    chosen = render(src, PageStyle(font_size=40, lang="de", bar_position="off")).pages[0]
    book_language = render(src, PageStyle(font_size=40, lang="en", bar_position="off")).pages[0]
    assert auto == book_language  # auto is the language of the book
    assert chosen != auto  # and "de" hyphenates the compound words in German


# The progress bar


def test_the_bar_is_at_the_bottom_by_default_and_at_the_top_on_request(tmp_path):
    src = book(tmp_path, SHORT)  # the text stays above the bottom margin
    bottom = page(render(src))
    top = page(render(src, PageStyle(bar_position="top")))
    assert ink(bottom, (0, 800 - 30, 480, 800)) is not None
    assert ink(top, (0, 0, 480, 30)) is not None
    assert ink(top, (0, 800 - 30, 480, 800)) is None
    # The bar takes 14 + 2 * 4 px at the edge: its text sits 4 px from it, in a row of 14.
    left, upper, _, lower = ink(top, (0, 0, 480, 22))
    assert 15 <= left <= 17 and 4 <= upper and lower <= 18


def test_the_bar_can_be_off(tmp_path):
    im = page(render(book(tmp_path, SHORT), PageStyle(bar_position="off")))
    assert ink(im, (0, 800 - 30, 480, 800)) is None


def test_the_bar_line_is_two_px_and_shows_the_progress_of_the_book(tmp_path):
    src = book(tmp_path, THREE)
    style = PageStyle(bar_line=True, **QUIET)
    r = render(src, style)
    assert len(r.pages) == 3
    for n in range(3):
        im = page(r, n)
        assert ink(im, (0, 700, 480, 800)) == (16, 794, 464, 796)  # the content width, 2 px
        read = round(448 * (n + 1) / 3)
        assert {im.getpixel((x, y)) for x in range(16, 16 + read) for y in (794, 795)} == {0}
        track = {im.getpixel((x, y)) for x in range(16 + read, 464) for y in (794, 795)}
        assert track <= {170}  # light gray, a level that XTH has
        assert (track == {170}) == (n < 2)  # and the last page has no track left


def test_the_bar_line_can_span_the_page_and_sit_at_the_top(tmp_path):
    src = book(tmp_path, THREE)
    full = page(render(src, PageStyle(bar_line=True, bar_full_width=True, **QUIET)))
    assert ink(full, (0, 700, 480, 800)) == (0, 794, 480, 796)
    top = page(render(src, PageStyle(bar_line=True, bar_position="top", **QUIET)))
    assert ink(top, (0, 0, 480, 22)) == (16, 4, 464, 6)


def test_chapter_marks_are_ticks_that_reach_past_the_line_at_the_chapter_starts(tmp_path):
    src = book(tmp_path, THREE)
    r = render(src, PageStyle(bar_line=True, bar_chapter_marks=True, **QUIET))
    im = page(r)
    assert ink(im, (0, 700, 480, 800)) == (16, 792, 464, 798)  # 6 px: 2 more on each side
    for start in (1 / 3, 2 / 3):  # B and C start there; A starts with the book and has none
        x = 16 + round(448 * start)
        assert [im.getpixel((x, y)) for y in range(790, 800)] == [255] * 2 + [0] * 6 + [255] * 2
    assert im.getpixel((16 + round(448 * 0.5), 792)) == 255  # none between them
    marked = [x for x in range(16, 464) if im.getpixel((x, 792)) == 0]
    assert len(marked) == 4  # two ticks of 2 px


def test_marks_need_the_line(tmp_path):
    src = book(tmp_path, THREE)
    r = render(src, PageStyle(bar_chapter_marks=True, **QUIET))
    assert ink(page(r), (0, 700, 480, 800)) is None


def bar_text(src, style, tmp_path):
    """The last line of each page of a PDF: the bar's row of text."""
    return [text.splitlines()[-1] for text in pdf_pages(src, style, tmp_path)[0]]


def test_the_bar_shows_the_title_and_the_page_by_default(tmp_path):
    texts = bar_text(book(tmp_path, THREE), PageStyle(), tmp_path)
    assert texts == ["A  \u00b7  1 / 3", "B  \u00b7  2 / 3", "C  \u00b7  3 / 3"]


def test_the_bar_joins_its_parts_in_one_order(tmp_path):
    every = PageStyle(bar_book_percent=True, bar_chapter_page=True, bar_chapter_percent=True)
    texts = bar_text(book(tmp_path, THREE), every, tmp_path)
    assert texts[1] == "B  \u00b7  2 / 3  \u00b7  67%  \u00b7  1 / 1  \u00b7  100%"


@pytest.mark.parametrize(
    "switch, expected",
    [
        ({"bar_chapter_title": False}, "2 / 3"),
        ({"bar_page": False}, "B"),
        ({"bar_page": False, "bar_book_percent": True}, "B  \u00b7  67%"),
        ({"bar_page": False, "bar_chapter_page": True}, "B  \u00b7  1 / 1"),
        ({"bar_page": False, "bar_chapter_percent": True}, "B  \u00b7  100%"),
    ],
)
def test_each_part_of_the_bar_has_its_own_switch(tmp_path, switch, expected):
    assert bar_text(book(tmp_path, THREE), PageStyle(**switch), tmp_path)[1] == expected


def test_a_bar_without_parts_draws_no_text(tmp_path):
    im = page(render(book(tmp_path, THREE), PageStyle(**QUIET)))
    assert ink(im, (0, 700, 480, 800)) is None


def test_chapter_numbers_count_the_pages_of_the_chapter(tmp_path):
    src = book(tmp_path, f"# Short\n\nx\n\n# Long\n\n{LONG}\n\n# Last\n\ny\n")
    style = PageStyle(bar_page=False, bar_chapter_page=True, bar_chapter_percent=True)
    rendered = render(src, style)
    texts = bar_text(src, style, tmp_path)
    assert len(texts) == len(rendered.pages)
    starts = [start for _, start in rendered.chapters] + [len(texts)]
    expected = []
    for (title, _), first, after in zip(rendered.chapters, starts, starts[1:], strict=False):
        for n in range(first, after):
            number, count = n - first + 1, after - first
            percent = math.floor(100 * number / count + 0.5)  # half up, as Typst rounds
            expected.append(f"{title}  \u00b7  {number} / {count}  \u00b7  {percent}%")
    assert texts == expected
    assert len(rendered.pages) > 4  # the long chapter has several pages


def test_text_before_the_first_chapter_is_a_chapter_without_a_title(tmp_path):
    src = book(tmp_path, f"Intro.\n\n# One\n\n{LONG}\n")
    style = PageStyle(bar_page=False, bar_chapter_page=True)
    texts = bar_text(src, style, tmp_path)
    assert texts[0] == "1 / 1"  # the page of the intro, which `# One` ends
    assert texts[1] == f"One  \u00b7  1 / {len(texts) - 1}"


def test_the_bar_size_and_margins_place_its_text(tmp_path):
    src = book(tmp_path, SHORT)

    def row(**style):
        return ink(page(render(src, PageStyle(**style))), (0, 700, 480, 800))

    default = row()
    assert 15 <= default[0] <= 17 and 782 <= default[1] and default[3] <= 796  # 4 px from the edge
    assert row(bar_edge_margin=12)[3] <= 800 - 12
    assert row(bar_side_margin=40)[0] >= 40 and row(bar_side_margin=0)[0] < 4
    tall = row(bar_font_size=24)
    assert tall[3] - tall[1] > default[3] - default[1]
    assert tall[3] <= 800 - 4 and tall[1] >= 800 - 32  # in the 24 + 2 * 4 px that it takes


def test_the_bar_takes_its_room_from_the_text(tmp_path):
    src = book(tmp_path, FILLER)
    for style, bottom in [
        (PageStyle(), 800 - 16 - 22),
        (PageStyle(bar_font_size=24, bar_edge_margin=8), 800 - 16 - 40),
        (PageStyle(bar_position="top"), 800 - 16),
        (PageStyle(bar_position="off"), 800 - 16),
    ]:
        body = ink(page(render(src, style)), (0, 40, 480, 760))
        assert body[3] <= bottom + OVERHANG
    top = ink(page(render(src, PageStyle(bar_position="top"))), (0, 22, 480, 400))
    assert top[1] >= 22 + 16 - OVERHANG  # the text starts below the bar and the margin
    off = ink(page(render(src, PageStyle(bar_position="off"))), (0, 0, 480, 400))
    assert off[1] < top[1] - 15  # which it would not, with no bar on that side


@pytest.mark.parametrize("position", ["bottom", "top"])
@pytest.mark.parametrize("edge", [0, 1, 2, 3, 4, 8])
def test_the_bar_area_holds_everything_the_bar_draws(tmp_path, position, edge):
    # With no margin, the area that the bar reserves is where the text ends and its own begins
    style = PageStyle(margin=0, bar_edge_margin=edge, bar_line=True, bar_position=position)
    tall = picture(tmp_path, (100, 3000), name="tall.png")  # as tall as the text area is
    [[(_, top, _, bottom)]] = render(book(tmp_path, f"![]({tall})\n"), style).image_boxes
    alone = render(book(tmp_path, "<!-- page: 1 -->\n", "empty.md"), style)  # a page of the bar
    bar = ink(page(alone), (0, 0, 480, 800))
    area = max(14 + 2 * edge, 14 + edge + 4)  # a line, and the ticks that reach 4 px past its edge
    if position == "bottom":
        assert 800 - bottom == area and bar[1] >= bottom
    else:
        assert top == area and bar[3] <= top


def test_a_title_longer_than_the_row_is_cut_and_the_numbers_stay(tmp_path):
    title = "A chapter title that runs on and on and on and on past the end of the row"
    src = book(tmp_path, f"# {title}\n\ntext\n")
    text = bar_text(src, PageStyle(bar_book_percent=True), tmp_path)[0]
    shown, _, numbers = text.partition("  \u00b7  1 / 1")
    assert title.startswith(shown) and len(shown) < len(title)
    assert numbers == "  \u00b7  100%"
    im = page(render(src, PageStyle(bar_book_percent=True)))
    assert ink(im, (0, 700, 480, 800))[2] <= 464  # inside the side margin


# Twelve chapters of one page each: from page 10 the numbers have two digits. At a font size of 32 px
# the row is 320 px (side margins of 80), "12 / 12 \u00b7 100% \u00b7 1 / 1" is 296 px wide, which leaves no
# room for a letter of the title, and the four numbers together are 409 px, which cannot fit.
TWELVE = "\n\n".join(f"# Chapter {n}\n\ntext" for n in range(1, 13)) + "\n"
WIDEST = {
    "bar_font_size": 32,
    "bar_side_margin": 80,
    "bar_book_percent": True,
    "bar_chapter_page": True,
    "bar_chapter_percent": True,
}


def test_a_title_has_no_room_when_the_numbers_fill_the_row(tmp_path):
    style = PageStyle(**{**WIDEST, "bar_chapter_percent": False})
    last = bar_text(book(tmp_path, TWELVE), style, tmp_path)[-1]
    assert last == "12 / 12  \u00b7  100%  \u00b7  1 / 1"


def test_numbers_that_do_not_fit_the_row_are_dropped_whole_and_the_bar_stays_in_its_area(tmp_path):
    src = book(tmp_path, TWELVE)
    for position, band in (("top", (0, 0, 480, 50)), ("bottom", (0, 130, 480, 800))):
        r = render(src, PageStyle(bar_position=position, **WIDEST))
        assert len(r.pages) == 12
        for n in range(12):  # the bar's area is 32 + 2 * 4 px, and its row is the 320 px between
            left, top, right, bottom = ink(page(r, n), band)  # the side margins, from x = 80
            in_area = bottom <= 40 if position == "top" else top >= 800 - 40
            assert in_area and 79 <= left and right <= 401, (position, n + 1)
    last = bar_text(src, PageStyle(**WIDEST), tmp_path)[-1]
    assert last == "12 / 12  \u00b7  100%  \u00b7  1 / 1"  # the last number goes, not half of it


def test_a_number_that_alone_is_wider_than_the_row_is_not_drawn_at_all(tmp_path):
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    font = TTFont(FONTS_DIR / "bitter" / "Bitter-Regular.ttf")  # with digits ten times as wide
    for record in font["name"].names:
        if record.nameID in (1, 16):
            record.string = "Wide Digits"
    cmap = font.getBestCmap()
    for digit in "0123456789":
        advance, left = font["hmtx"].metrics[cmap[ord(digit)]]
        font["hmtx"].metrics[cmap[ord(digit)]] = (advance * 10, left)
    font.save(fonts / "wide.ttf")
    src = book(tmp_path, TWELVE)  # a heading with wide digits takes lines, so look at the bar only
    for position, band in (("top", (0, 0, 480, 50)), ("bottom", (0, 700, 480, 800))):
        style = PageStyle(font="Wide Digits", bar_position=position, **WIDEST)
        r = render(src, style, font_extra_dirs=[fonts])
        # "1 / 12" alone is 457 px in it, the row is 320, and half of it would read as another number
        assert [ink(page(r, n), band) for n in range(12)] == [None] * 12


# Orientation


@pytest.mark.parametrize("orientation", [90, 270])
def test_a_turned_page_is_the_screen_of_the_device(tmp_path, orientation):
    src = book(tmp_path, SHORT)
    normal = render(src, device="x3")
    turned = render(src, PageStyle(orientation=orientation), device="x3")
    assert page(turned).size == (528, 792) == page(normal).size
    assert turned.pages[0] != normal.pages[0]


def test_the_bar_is_at_the_edge_that_the_orientation_makes_the_bottom(tmp_path):
    src = book(tmp_path, SHORT)
    edge = {  # where the strip of the bar is, in the screen's own pixels
        0: (0, 800 - 30, 480, 800),
        90: (0, 0, 30, 800),  # a page that is turned clockwise has its bottom on the left
        180: (0, 0, 480, 30),
        270: (480 - 30, 0, 480, 800),
    }
    for orientation, strip in edge.items():
        bar = ink(page(render(src, PageStyle(orientation=orientation))), strip)
        assert bar is not None
        opposite = ink(
            page(render(src, PageStyle(orientation=orientation, bar_position="off"))), strip
        )
        assert opposite is None  # only the bar was there


def test_orientations_are_the_same_layout_turned(tmp_path):
    src = book(tmp_path, LONG)
    page0 = page(render(src, PageStyle(orientation=0)))
    page180 = page(render(src, PageStyle(orientation=180)))
    assert ImageChops.difference(page0.rotate(180), page180).getbbox() is None
    page90 = page(render(src, PageStyle(orientation=90)))
    page270 = page(render(src, PageStyle(orientation=270)))
    assert ImageChops.difference(page90.rotate(180), page270).getbbox() is None


def test_a_book_turned_on_its_side_has_the_pages_of_a_wide_page(tmp_path):
    src = book(tmp_path, LONG)
    upright = render(src, PageStyle(orientation=0))
    sideways = render(src, PageStyle(orientation=90))
    assert len(sideways.pages) > len(upright.pages)  # a page of 800 x 480 holds fewer lines


# Image boxes


def size_of(box) -> tuple[int, int]:
    """A box takes every pixel its image touches: 1 px more where the image is between pixels."""
    return box[2] - box[0], box[3] - box[1]


def picture(tmp_path, size=(80, 60), value=100, name="a.png"):
    Image.new("L", size, value).save(tmp_path / name)
    return name


@pytest.mark.parametrize("orientation", [0, 90, 180, 270])
def test_a_page_with_one_image_reports_the_box_that_the_image_covers(tmp_path, orientation):
    name = picture(tmp_path)
    r = render(
        book(tmp_path, f"![]({name})\n"), PageStyle(bar_position="off", orientation=orientation)
    )
    [[box]] = r.image_boxes
    im = page(r)
    assert ink(im, (0, 0, *im.size)) == box  # the pixels of the image, and nothing else
    assert 0 <= box[0] < box[2] <= im.width and 0 <= box[1] < box[3] <= im.height
    assert sorted((box[2] - box[0], box[3] - box[1])) == [60, 80]


def test_a_page_with_one_image_has_exactly_one_box_inside_the_page(tmp_path):
    name = picture(tmp_path)
    r = render(book(tmp_path, f"# One\n\n![]({name})\n"))
    assert len(r.pages) == len(r.image_boxes) == 1 and len(r.image_boxes[0]) == 1
    [[(x0, y0, x1, y1)]] = r.image_boxes
    assert size_of((x0, y0, x1, y1)) in {(80, 60), (80, 61)}
    assert 0 <= x0 and x1 <= 480 and 0 <= y0 and y1 <= 800


def test_the_box_is_the_image_and_not_its_caption(tmp_path):
    name = picture(tmp_path)  # the caption is wider than the image
    r = render(
        book(tmp_path, f"![A picture with a caption]({name})\n"), PageStyle(bar_position="off")
    )
    [[box]] = r.image_boxes
    assert box == (200, 16, 280, 76)
    im = page(r)
    assert ink(im, (0, 0, 480, 90)) == box  # above the caption
    assert ink(im, (0, 90, 480, 800)) is not None  # which is there, below


def test_the_box_of_a_vector_image_is_its_frame(tmp_path):
    (tmp_path / "v.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20"/></svg>'
    )
    r = render(book(tmp_path, "![](v.svg)\n"), PageStyle(bar_position="off"))
    [[(x0, y0, x1, y1)]] = r.image_boxes
    assert (x0, x1) == (16, 464)  # the body, the way it is laid out
    ink_box = ink(page(r), (0, 0, 480, 800))
    assert x0 <= ink_box[0] and ink_box[2] <= x1 and y0 <= ink_box[1] and ink_box[3] <= y1


QUOTED_FRAMES = {
    # A quote leaves 1 em (32 px) at its left, so the frame of a vector image in one is the body
    # from x = 16 + 32, in the pixels of the turned page: 480 x 800 laid out, or 800 x 480 for 90
    # and 270, and the box is turned with it.
    0: (48, 16, 464, 784),
    90: (16, 48, 464, 784),
    180: (16, 16, 432, 784),
    270: (16, 16, 464, 752),
}


@pytest.mark.parametrize("orientation", [0, 90, 180, 270])
def test_the_box_of_a_vector_image_in_a_quote_is_its_frame(tmp_path, orientation):
    (tmp_path / "v.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20"/></svg>'
    )
    r = render(
        book(tmp_path, "> ![](v.svg)\n"), PageStyle(bar_position="off", orientation=orientation)
    )
    assert r.image_boxes == [[QUOTED_FRAMES[orientation]]]  # not as wide as the body is
    x0, y0, x1, y1 = QUOTED_FRAMES[orientation]
    left, top, right, bottom = ink(page(r), (x0, y0, x1, y1))
    side = min(x1 - x0, y1 - y0)  # the square image fills the short side of its frame
    assert (right - left, bottom - top) == (side, side)  # and the box holds all of it


def test_a_tall_image_with_a_caption_keeps_its_box_in_the_body(tmp_path):
    name = picture(tmp_path, (100, 1000))
    caption = " ".join(["word"] * 30)
    r = render(book(tmp_path, f"![{caption}]({name})\n"))
    [[(x0, y0, x1, y1)]] = r.image_boxes
    assert 16 <= x0 and x1 <= 480 - 16 and 16 <= y0 and y1 <= 800 - 16 - 22
    assert y1 - y0 < 1000  # scaled down to leave the caption its place


def test_every_image_has_its_box_on_its_own_page(small_book):
    r = render(load_source(small_book))
    assert [len(boxes) for boxes in r.image_boxes] == [1, 1]
    (picture_box,), (twin_box,) = r.image_boxes  # the picture, and the image of the wide table
    assert size_of(picture_box) in {(80, 60), (80, 61)}
    assert size_of(twin_box) in {(240, 90), (240, 91)}


def test_text_and_tables_have_no_box(tmp_path):
    rows = "<tr>" + "<td>x</td>" * 3 + "</tr>"
    r = render(book(tmp_path, f"# Text\n\nWords.\n\n<table>{rows}</table>\n"))
    assert r.image_boxes == [[]]
    big = "<tr><td>x</td></tr>" * 20_001
    r = render(book(tmp_path, f"<table>{big}</table>\n\nafter\n", "big.md"))
    assert r.image_boxes == [[]]  # "Table too large to preview" is no image


def test_the_stock_view_has_no_image_and_so_no_box(small_book):
    r = render(load_source(small_book), view="stock")
    assert r.image_boxes == [[], []]


def test_images_that_are_dropped_have_no_box(tmp_path, small_book):
    profile = image_profile(Options(device="x4", size="small", firmware="stock"))
    r = render(load_source(small_book), image_profile=profile)
    assert r.image_boxes == [[], []]


def test_several_images_on_a_page_each_have_a_box(tmp_path):
    name = picture(tmp_path, (60, 40))
    r = render(
        book(tmp_path, f"![]({name})\n\n![]({name})\n\n![]({name})\n"),
        PageStyle(bar_position="off"),
    )
    [boxes] = r.image_boxes
    assert len(boxes) == 3 and boxes == sorted(boxes, key=lambda b: b[1])
    assert all(size_of(box) in {(60, 40), (60, 41)} for box in boxes)
    assert len({b[1] for b in boxes}) == 3  # one below the other


def test_the_box_of_an_image_on_a_later_page_is_on_that_page(tmp_path):
    name = picture(tmp_path)
    r = render(book(tmp_path, f"# One\n\n{LONG}\n\n![]({name})\n"))
    assert len(r.pages) > 1
    assert [len(boxes) for boxes in r.image_boxes] == [0] * (len(r.pages) - 1) + [1]
    assert ink(page(r, len(r.pages) - 1), r.image_boxes[-1][0]) is not None


def test_an_excerpt_has_the_boxes_of_the_book(small_book):
    src = load_source(small_book)
    style = PageStyle(bar_position="off")
    full = render(src, style)
    for chapter in (0, 1):
        part, _ = render_chapter(src, device="x4", style=style, view="xtc", chapter=chapter)
        assert part.image_boxes == [full.image_boxes[chapter]]


def test_the_boxes_are_kept_with_the_cache(tmp_path, small_book):
    cache = tmp_path / "cache"
    first = render(load_source(small_book), cache_dir=cache)
    assert json.loads((cache / "map.json").read_text())["boxes"] == [
        [list(box) for box in boxes] for boxes in first.image_boxes
    ]
    again = render(load_source(small_book), cache_dir=cache)
    assert again == first and again.image_boxes[0] != []
    assert isinstance(again.image_boxes[0][0], tuple)


def test_a_cache_from_before_the_boxes_is_rendered_again(tmp_path, small_book):
    cache = tmp_path / "cache"
    render(load_source(small_book), cache_dir=cache)
    data = json.loads((cache / "map.json").read_text())
    del data["boxes"]
    (cache / "map.json").write_text(json.dumps(data))
    assert pages_module.read_map(cache) is None
    assert render(load_source(small_book), cache_dir=cache).image_boxes[0] != []
    assert pages_module.read_map(cache) is not None


# Excerpts and the bar


def test_the_chapter_numbers_of_the_bar_are_the_same_in_an_excerpt(small_book):
    src = load_source(small_book)
    style = PageStyle(bar_page=False, bar_chapter_page=True, bar_chapter_percent=True)
    full = render(src, style)
    for chapter in (0, 1):
        part, _ = render_chapter(src, device="x4", style=style, view="xtc", chapter=chapter)
        assert part.pages == [full.pages[chapter]]  # chapters start on their own page


def test_an_excerpt_differs_from_the_book_only_in_the_numbers_of_the_book(small_book):
    src = load_source(small_book)
    full = render(src)
    part, index = render_chapter(src, device="x4", style=PageStyle(), view="xtc", chapter=1)
    difference = ImageChops.difference(page(part, index), page(full, 1))
    assert difference.crop((0, 0, 480, 800 - 38)).getbbox() is None  # the text is the same
    assert difference.crop((0, 800 - 38, 480, 800)).getbbox() is not None  # "1 / 1" and "2 / 3"


def test_with_the_bar_off_an_excerpt_is_the_page_of_the_book(small_book):
    src = load_source(small_book)
    style = PageStyle(bar_position="off", font="Bitter", font_weight=600, align="left")
    full = render(src, style)
    for chapter in (0, 1):
        part, _ = render_chapter(src, device="x4", style=style, view="xtc", chapter=chapter)
        assert part.pages == [full.pages[chapter]]


# Fonts that were uploaded


def test_an_uploaded_font_is_found_in_its_folder(tmp_path):
    folder = tmp_path / "fonts"
    folder.mkdir()
    font = TTFont(FONTS_DIR / "bitter" / "Bitter-Regular.ttf")
    for record in font["name"].names:
        if record.nameID in (1, 16):  # the family
            record.string = "Uploaded Test"
    font.save(folder / "uploaded.ttf")
    src = book(tmp_path, "Plain words with no heading.\n")
    uploaded = PageStyle(font="Uploaded Test")
    with_folder = render(src, uploaded, font_extra_dirs=[folder]).pages[0]
    assert with_folder == render(src, PageStyle(font="Bitter")).pages[0]  # the same glyphs
    assert render(src, uploaded).pages[0] != with_folder  # without it Typst takes another font
    part, _ = render_chapter(
        src, device="x4", style=uploaded, view="xtc", chapter=0, font_extra_dirs=[folder]
    )
    assert part.pages[0] == with_folder  # and an excerpt finds it too
