import re
from dataclasses import fields

import pytest
import typst
from fontTools.ttLib import TTFont

from eco.style import (
    BUNDLED_FONTS,
    FONTS_DIR,
    PageStyle,
    available_weights,
    font_dirs,
)


def test_defaults_match_spec():
    s = PageStyle()
    assert (
        s.font,
        s.font_size,
        s.font_weight,
        s.line_height,
        s.margin,
        s.align,
        s.mode,
        s.dither_strength,
    ) == ("Literata", 32, 400, 135, 16, "justify", "xth", 80)


def test_every_default_of_the_table():
    assert PageStyle().to_json() == {
        "font": "Literata",
        "font_size": 32,
        "font_weight": 400,
        "line_height": 135,
        "margin_x": 16,
        "margin_y": 16,
        "paragraph_spacing": 120,
        "first_line_indent": 0,
        "focus_mode": False,
        "focus_weight": 600,
        "align": "justify",
        "hyphenate": True,
        "lang": "auto",
        "mode": "xth",
        "dither": True,
        "dither_strength": 80,
        "negative": False,
        "bar_position": "bottom",
        "bar_line": False,
        "bar_page": True,
        "bar_book_percent": False,
        "bar_chapter_page": False,
        "bar_chapter_percent": False,
        "bar_chapter_title": True,
        "bar_chapter_marks": False,
        "bar_full_width": False,
        "bar_font_size": 14,
        "bar_edge_margin": 4,
        "bar_side_margin": 16,
        "orientation": 0,
    }


def test_json_round_trip_and_errors():
    assert (
        PageStyle.from_json(PageStyle(font="Bitter", font_weight=700).to_json()).font_weight == 700
    )
    with pytest.raises(ValueError, match="font_size"):
        PageStyle.from_json({"font_size": 500})
    with pytest.raises(ValueError, match="Unknown style field: colour"):
        PageStyle.from_json({"colour": "red"})


def test_a_partial_object_takes_the_defaults_for_the_rest():
    assert PageStyle.from_json({"margin": 20}) == PageStyle(margin=20)
    assert PageStyle.from_json({}) == PageStyle()


def test_weights():
    assert available_weights("Lexend Deca") == [400, 500, 600, 700, 800]
    assert available_weights("Literata") == [400, 500, 600, 700, 800]
    assert available_weights("Bitter") == [400, 500, 600, 700, 800]
    assert available_weights("Libertinus Serif") == [400, 600, 700]  # what Typst embeds
    assert available_weights("No Such Font") == []


@pytest.mark.parametrize(
    "name,low,high",
    [
        ("font_size", 16, 64),
        ("line_height", 100, 250),
        ("margin", 0, 80),
        ("dither_strength", 0, 100),
        ("bar_font_size", 8, 32),
        ("bar_edge_margin", 0, 40),
        ("bar_side_margin", 0, 80),
    ],
)
def test_a_number_takes_its_whole_range_and_nothing_else(name, low, high):
    for ok in (low, high):
        style = PageStyle.from_json({name: ok})
        if name == "margin":
            assert (style.margin_x, style.margin_y) == (ok, ok)
        else:
            assert getattr(style, name) == ok
    for bad in (low - 1, high + 1, True, "32", 32.0, 32.5, None, [32]):
        with pytest.raises(ValueError, match=f"{name} must be a whole number from {low} to {high}"):
            PageStyle.from_json({name: bad})


@pytest.mark.parametrize(
    "name,good,bad",
    [
        ("align", ["justify", "left"], ["right", "Justify", "justify ", 1]),
        ("mode", ["xth", "xtg"], ["xtc", "XTH", None]),
        ("bar_position", ["bottom", "top", "off"], ["middle", False, True]),
        ("orientation", [0, 90, 180, 270], [45, 360, False, True, "90", 90.0]),
    ],
)
def test_a_choice_takes_exactly_its_values(name, good, bad):
    for ok in good:
        assert getattr(PageStyle.from_json({name: ok}), name) == ok
    for value in bad:
        with pytest.raises(ValueError, match=f"{name} must be one of"):
            PageStyle.from_json({name: value})


@pytest.mark.parametrize(
    "name",
    [
        f.name
        for f in fields(PageStyle)
        if isinstance(f.default, bool)  # the flags: hyphenate, dither, negative and the bar_ ones
    ],
)
def test_a_flag_is_a_real_boolean(name):
    assert getattr(PageStyle.from_json({name: not getattr(PageStyle(), name)}), name) is (
        not getattr(PageStyle(), name)
    )
    for bad in (1, 0, "true", None, "yes"):
        with pytest.raises(ValueError, match=f"{name} must be true or false"):
            PageStyle.from_json({name: bad})


def test_there_are_flags():
    assert len([f for f in fields(PageStyle) if isinstance(f.default, bool)]) == 12


@pytest.mark.parametrize("lang", ["auto", "en", "id", "fil", "de"])
def test_a_language_is_auto_or_a_plain_code(lang):
    assert PageStyle.from_json({"lang": lang}).lang == lang


@pytest.mark.parametrize(
    "lang",
    ["", "e", "english", "EN", "en-US", "en\n", '"', 'en")\n#read("x")', 1, None, "e1", " en"],
)
def test_a_language_that_is_not_a_plain_code_is_refused(lang):
    with pytest.raises(ValueError, match="lang must be"):
        PageStyle.from_json({"lang": lang})


def test_a_font_must_be_a_known_family():
    assert PageStyle.from_json({"font": "Libertinus Serif"}).font == "Libertinus Serif"
    for bad in ("Comic Sans", "", None, 3, '"); #read("x")'):
        with pytest.raises(ValueError, match="font must be"):
            PageStyle.from_json({"font": bad})


def test_a_weight_must_be_one_of_the_font():
    assert PageStyle.from_json({"font": "Libertinus Serif", "font_weight": 600}).font_weight == 600
    with pytest.raises(ValueError, match="font_weight must be one of: 400, 600, 700"):
        PageStyle.from_json({"font": "Libertinus Serif", "font_weight": 500})
    for bad in ("400", 400.0, True, None, 450):
        with pytest.raises(ValueError, match="font_weight must be one of"):
            PageStyle.from_json({"font_weight": bad})


def test_a_style_must_be_an_object():
    for bad in ([], "x", None, 5):
        with pytest.raises(ValueError, match="style must be an object"):
            PageStyle.from_json(bad)


def test_a_style_built_in_code_is_checked_too():
    with pytest.raises(ValueError, match="font_size"):
        PageStyle(font_size=500)
    with pytest.raises(ValueError, match="bar_position"):
        PageStyle(bar_position="left")


@pytest.fixture
def uploads(tmp_path):
    """A folder with one uploaded family, "Test Sans", made from a bundled font."""
    font = TTFont(BUNDLED_FONTS["Lexend Deca"][700])
    for record in font["name"].names:
        if record.nameID in (1, 4, 6, 16):
            record.string = "Test Sans" if record.nameID != 6 else "TestSans-Bold"
    folder = tmp_path / "fonts"
    folder.mkdir()
    font.save(folder / "test.ttf")
    return folder


def test_an_uploaded_family_is_known_with_its_extra_dir(uploads):
    assert available_weights("Test Sans") == []
    assert available_weights("Test Sans", [uploads]) == [700]
    style = PageStyle.from_json({"font": "Test Sans", "font_weight": 700}, extra_dirs=[uploads])
    assert style.font == "Test Sans"
    with pytest.raises(ValueError, match="font must be"):
        PageStyle.from_json({"font": "Test Sans"})
    with pytest.raises(ValueError, match="font_weight must be one of: 700"):
        PageStyle.from_json({"font": "Test Sans", "font_weight": 400}, extra_dirs=[uploads])


def test_a_folder_that_does_not_exist_is_no_font(tmp_path):
    assert available_weights("Test Sans", [tmp_path / "none"]) == []


def test_font_dirs_are_the_bundled_ones_then_the_uploads(tmp_path):
    bundled = font_dirs()
    assert bundled and all(d.is_dir() and d.is_relative_to(FONTS_DIR) for d in bundled)
    assert font_dirs([tmp_path]) == [*bundled, tmp_path]


def test_the_bundled_table_names_the_fonts_that_are_there():
    assert sorted(BUNDLED_FONTS) == ["Bitter", "Lexend Deca", "Literata"]
    found = typst.Fonts(
        include_system_fonts=False,
        include_embedded_fonts=False,
        font_paths=[str(d) for d in font_dirs()],
    )
    weights = {}
    for f in found.fonts():
        if f.style == "normal":
            weights.setdefault(f.family, set()).add(f.weight)
    assert weights == {family: set(files) for family, files in BUNDLED_FONTS.items()}
    for files in BUNDLED_FONTS.values():
        for weight, path in files.items():
            assert path.is_file()
            assert TTFont(path)["OS/2"].usWeightClass == weight
            assert "fvar" not in TTFont(path)  # static instances only


def test_literata_has_an_italic():
    found = typst.Fonts(
        include_system_fonts=False,
        include_embedded_fonts=False,
        font_paths=[str(FONTS_DIR / "literata")],
    )
    assert [(f.family, f.style, f.weight) for f in found.fonts() if f.style == "italic"] == [
        ("Literata", "italic", 400)
    ]


def test_the_fonts_are_small_open_and_say_where_they_came_from():
    size = sum(p.stat().st_size for p in FONTS_DIR.rglob("*") if p.is_file())
    assert size <= 6 * 1024 * 1024
    for folder in font_dirs():
        licence = (folder / "OFL.txt").read_text(encoding="utf-8")
        assert "SIL Open Font License, Version 1.1" in licence
    sources = (FONTS_DIR / "SOURCES.md").read_text(encoding="utf-8")
    for family in BUNDLED_FONTS:
        assert re.search(rf"^## {family}$", sources, re.MULTILINE)
    assert sorted(p.suffix for p in FONTS_DIR.rglob("*") if p.is_file()) == sorted(
        [".ttf"] * 16 + [".txt"] * 3 + [".md"]
    )
