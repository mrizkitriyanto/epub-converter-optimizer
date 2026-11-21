import time
from collections import Counter

import pytest

from eco.epub.css import rewrite_css


def keep(ref):
    return ref


def renamed(ref):
    if "gone" in ref:
        return None
    return ref.replace("a.png", "a.jpg")


def test_xteink_drops_layout_declarations_only():
    css = (
        ".a { float: left; width: 40% }\n"
        ".b { display: flex !important; justify-content: center }\n"
        ".c { display:inline-grid;text-align:left }\n"
        ".d { display: block; -webkit-columns: 2; column-count: 3 }\n"
        ".e { position: absolute; top: 0 }\n"
        "@media screen and (max-width: 100px) { p { text-align: left; float: none } }\n"
    )
    assert rewrite_css(css, keep, xteink=True) == (
        ".a {  width: 40% }\n"
        ".b {  justify-content: center }\n"
        ".c { text-align:left }\n"
        ".d { display: block;  }\n"
        ".e {  top: 0 }\n"
        "@media screen and (max-width: 100px) { p { text-align: left; } }\n"
    )


def test_general_keeps_every_declaration():
    css = ".a { float: left; display: flex; position: absolute; columns: 2 }"
    assert rewrite_css(css, keep) == css


def test_xteink_drops_font_faces_and_comments_but_not_strings():
    css = (
        "/* float: left; */\n@font-face { font-family: F; src: url(f.otf) }\n"
        'p::before { content: "}; float: x"; text-align: left }'
    )
    out = rewrite_css(css, keep, xteink=True)
    assert "@font-face" not in out and "/*" not in out
    assert 'content: "}; float: x"; text-align: left' in out


def test_urls_follow_renames_in_any_quoting_and_a_removed_file_takes_its_declaration():
    css = (
        ".a { background: url(../img/a.png) }\n"
        '.b { background: url( "../img/a.png" ) no-repeat; color: red }\n'
        ".c { background: url('../img/gone.png'); height: 1em }\n"
        "@import url(other.css) screen and (min-width: 1px);\n"
    )
    assert rewrite_css(css, renamed) == (
        ".a { background: url(../img/a.jpg) }\n"
        '.b { background: url("../img/a.jpg") no-repeat; color: red }\n'
        ".c {  height: 1em }\n"
        "@import url(other.css) screen and (min-width: 1px);\n"
    )


def test_data_uris_with_semicolons_stay_in_one_piece():
    css = ".a { list-style-image: url(data:image/png;base64,AAAA;BBB); margin: 0 }"
    seen = []

    def spy(ref):
        seen.append(ref)
        return ref

    assert rewrite_css(css, spy, xteink=True) == css
    assert seen == ["data:image/png;base64,AAAA;BBB"]


def test_a_declaration_after_a_comment_still_follows_a_rename():
    css = ".a { /* the logo */ list-style-image: url(a.png) }\n.b {text-align: left; /* x */ float: left}"
    assert rewrite_css(css, renamed) == css.replace("a.png", "a.jpg")
    assert rewrite_css(css, renamed, xteink=True) == (
        ".a {  list-style-image: url(a.jpg) }\n.b {text-align: left;  }"
    )


def test_a_declaration_after_a_nested_block_or_behind_a_star_hack_is_rewritten():
    def to_jpg(ref):
        return ref.replace(".png", ".jpg")

    page = '@page { @top-center { content: "x" } background: url(bg.png) }'
    assert rewrite_css(page, to_jpg) == page.replace("bg.png", "bg.jpg")
    nested = "p { & b { text-align: left } float: left }"
    assert rewrite_css(nested, keep, xteink=True) == "p { & b { text-align: left } }"
    assert rewrite_css("p { *background: url(a.png) }", to_jpg) == "p { *background: url(a.jpg) }"
    assert rewrite_css("p { *float: left; text-align: left }", keep, xteink=True) == (
        "p {  text-align: left }"
    )


@pytest.mark.parametrize(
    "css",
    [
        "a:" * 16000 + "{",  # took 15.6 s at half this size
        "}a:(" * 8000,
        "{a:(" * 8000,
        '{a:"' * 8000,
        "{/*" * 10000,
        "{" + "a:b*/" * 6400,
        "body{margin:" + "1" * 16000 + "}",
        "p{margin:" + "1" * 16000 + "}",
        "p{font-size:" + "1" * 16000 + "}",
        "body{" + " " * 16000 + "}",
        "p{a:b" + " " * 16000 + "c}",
        "p{font:" + "1" * 16000 + "}",
        "p{font:" + "small " * 3000 + "}",
    ],
)
def test_crafted_css_takes_linear_time(css):
    start = time.perf_counter()
    for xteink in (False, True):
        rewrite_css(css, keep, xteink)
    assert time.perf_counter() - start < 1


def test_an_unclosed_comment_runs_to_the_end_of_the_text():
    assert rewrite_css("p { text-align: left } /* float: left", keep, xteink=True) == (
        "p { text-align: left } "
    )


def test_a_style_attribute_is_just_a_declaration_list():
    assert rewrite_css("float:left;text-align:left", keep, xteink=True) == "text-align:left"
    assert rewrite_css("text-align:left;float:left", keep, xteink=True) == "text-align:left;"
    assert rewrite_css("float:left", keep, xteink=True) == ""


# ------------------------------------------------- Xteink: relative sizes, no colors


def test_absolute_sizes_become_relative_on_xteink():
    css = (
        "p { font-size: 9pt; line-height: 14px } h1 { font-size: 24px; margin: 40px 0 } "
        ".k { font-size: x-small }"
    )
    out = rewrite_css(css, keep, xteink=True)
    assert "p { font-size: 0.75em; line-height: 1.2 }" in out
    assert "h1 { font-size: 1.5em; margin: 2em 0 }" in out
    assert ".k { font-size: 0.75em }" in out


def test_body_margins_go_on_xteink():
    out = rewrite_css(
        "html, body { margin: 40px; padding: 12pt; font-size: 12pt }", keep, xteink=True
    )
    assert "margin" not in out and "padding" not in out and "font-size: 1em" in out


def test_relative_sizes_are_left_alone():
    css = (
        "p { font-size: 1.1em; line-height: 1.4; margin: 1em } h2 { font-size: 120%; } "
        "q { font-size: 0.9rem; font-size: smaller !important }"
    )
    assert rewrite_css(css, keep, xteink=True) == css


def test_a_converted_value_keeps_important():
    assert "font-size: 1em !important" in rewrite_css(
        "p { font-size: 16px !important }", keep, True
    )


def test_text_and_background_colors_go_together():
    counts = Counter()
    out = rewrite_css(
        ".box { color: #fff; background-color: #222; border: 1px solid #000 }",
        keep,
        xteink=True,
        counts=counts,
    )
    assert "color: #fff" not in out and "background" not in out
    assert "border: 1px solid #000" in out
    assert counts["colors"] == 2


def test_general_keeps_sizes_and_colors():
    css = "p { font-size: 9pt; color: #777; background: #eee }"
    assert rewrite_css(css, keep, xteink=False) == css


def test_a_longer_property_name_is_not_a_page_box_margin():
    out = rewrite_css("html, body { -webkit-padding-start: 40px; font-size: 12pt }", keep, True)
    assert "-webkit-padding-start: 40px" in out and "font-size: 1em" in out


def test_body_with_a_class_and_page_rules_lose_margins():
    css = "body.calibre { margin: 40px } @page { margin: 1in } @page :first { margin: 2cm }"
    out = rewrite_css(css, keep, xteink=True)
    assert "margin" not in out


def test_a_body_class_rule_loses_margins_only():
    css = ".calibre { margin: 5pt; font-size: 12pt } .other { margin: 40px }"
    out = rewrite_css(css, keep, xteink=True, page_classes=frozenset({"calibre"}))
    assert ".calibre { font-size: 1em }" in out and ".other { margin: 2em }" in out


def test_a_page_box_declaration_list_loses_margins():
    out = rewrite_css("margin: 40px; color: #222; padding: 1em", keep, xteink=True, page_box=True)
    assert "margin" not in out and "padding: 1em" in out


def test_font_shorthand_sizes_become_relative():
    out = rewrite_css("p { font: italic 9pt/14px serif }", keep, xteink=True)
    assert "font: italic 0.75em/1.2 serif" in out
    out = rewrite_css("p { font: small-caps 12px serif }", keep, xteink=True)
    assert "font: small-caps 0.75em serif" in out
    assert (
        rewrite_css("p { font: 1em/1.4 serif }", keep, xteink=True) == "p { font: 1em/1.4 serif }"
    )
