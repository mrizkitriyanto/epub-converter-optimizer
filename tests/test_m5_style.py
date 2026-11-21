from io import BytesIO

import pytest
import typst
from pypdf import PdfReader

from eco.bookfolder import load_source
from eco.render.md2typst import to_typst
from eco.render.pages import render_book
from eco.style import CHOICES, PageStyle, font_dirs


def test_legacy_margin_migrates_to_both_axes():
    style = PageStyle.from_json({"margin": 27})
    assert (style.margin_x, style.margin_y) == (27, 27)
    assert "margin" not in style.to_json()
    assert PageStyle.from_json(style.to_json()) == style


def test_new_style_fields_and_defaults():
    style = PageStyle.from_json(
        {
            "margin_x": 25,
            "margin_y": 30,
            "align": "center",
            "paragraph_spacing": 160,
            "first_line_indent": 40,
        }
    )
    assert style.margin_x == 25 and style.margin_y == 30
    assert style.align == "center"
    assert style.paragraph_spacing == 160 and style.first_line_indent == 40
    assert PageStyle().paragraph_spacing == 120


@pytest.mark.parametrize(
    "field,value",
    [("margin_x", 81), ("margin_y", -1), ("paragraph_spacing", 301), ("first_line_indent", 401)],
)
def test_new_ranges(field, value):
    with pytest.raises(ValueError, match=field):
        PageStyle.from_json({field: value})


def test_new_settings_change_rendered_page(tmp_path):
    book = tmp_path / "book.md"
    book.write_text("# A\n\nA short paragraph.\n\nAnother paragraph.\n", encoding="utf-8")
    source = load_source(book)
    baseline = render_book(source, device="x4", style=PageStyle(), view="xtc").pages
    for change in (
        {"margin_x": 30},
        {"margin_y": 30},
        {"align": "center"},
        {"paragraph_spacing": 200},
        {"first_line_indent": 100},
    ):
        changed = render_book(
            source, device="x4", style=PageStyle.from_json(change), view="xtc"
        ).pages
        assert changed != baseline, change


def test_focus_mode_renders_body(tmp_path):
    book = tmp_path / "focus.md"
    book.write_text("# Heading\n\nHello café world.\n", encoding="utf-8")
    source = load_source(book)
    plain = render_book(source, device="x4", style=PageStyle(), view="xtc").pages
    focused = render_book(source, device="x4", style=PageStyle(focus_mode=True), view="xtc").pages
    assert focused != plain

    def text(style):
        root = tmp_path / ("focus" if style.focus_mode else "plain")
        root.mkdir()
        inputs = to_typst(source, device="x4", style=style, view="xtc")
        for name, content in inputs.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.read_bytes() if hasattr(content, "read_bytes") else content)
        pdf = typst.compile(
            root / "main.typ",
            root=str(root),
            format="pdf",
            ignore_system_fonts=True,
            font_paths=[str(p) for p in font_dirs()],
        )
        return "".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)

    assert text(PageStyle(focus_mode=True)) == text(PageStyle())


@pytest.mark.parametrize(
    "markdown", ["# Heading\n", "`code only`\n", "[Link text](https://example.com)\n"]
)
def test_focus_excludes_non_body_text(tmp_path, markdown):
    book = tmp_path / "exclude.md"
    book.write_text(markdown, encoding="utf-8")
    source = load_source(book)

    def pages(style):
        return render_book(source, device="x4", style=style, view="xtc").pages

    assert pages(PageStyle(focus_mode=True)) == pages(PageStyle())


def test_focus_rejects_a_font_without_heavier_weight():
    with pytest.raises(ValueError, match="no heavier weight"):
        PageStyle.from_json({"font": "Literata", "font_weight": 800, "focus_mode": True})


def test_focus_weight_replaces_strength():
    assert PageStyle().focus_weight == 700
    assert CHOICES["focus_weight"] == (600, 700, 800)
    assert "focus_strength" not in PageStyle().to_json()
    with pytest.raises(ValueError, match="focus_weight"):
        PageStyle(focus_weight=500)


def test_a_style_with_the_old_focus_strength_still_loads():
    style = PageStyle.from_json({"focus_mode": True, "focus_strength": "high"})
    assert style.focus_mode and style.focus_weight == 700


def test_focus_weight_must_be_heavier_than_the_text():
    data = {"font": "Literata", "font_weight": 600, "focus_mode": True, "focus_weight": 600}
    with pytest.raises(ValueError, match="heavier"):
        PageStyle.from_json(data)
    findings = []
    style = PageStyle.from_json(data, lenient=True, findings=findings)
    assert style.focus_weight == 700 and style.focus_mode
    assert [f.kind for f in findings] == ["focus_weight_raised"]


def test_extra_bold_needs_a_font_that_has_it():
    data = {"font": "Libertinus Serif", "focus_mode": True, "focus_weight": 800}
    with pytest.raises(ValueError, match="focus_weight 800"):
        PageStyle.from_json(data)
    findings = []
    style = PageStyle.from_json(data, lenient=True, findings=findings)
    assert style.focus_weight == 700 and [f.kind for f in findings] == ["focus_weight_missing"]
    assert PageStyle.from_json({**data, "font": "Literata"}).focus_weight == 800


def test_a_focus_weight_raised_goes_to_one_the_font_has():
    data = {"font": "Literata", "font_weight": 700, "focus_mode": True, "focus_weight": 700}
    style = PageStyle.from_json(data, lenient=True, findings=[])
    assert style.focus_weight == 800 and style.focus_mode
