import pytest

from eco.bookfolder import load_source
from eco.render.pages import render_book
from eco.style import PageStyle


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
