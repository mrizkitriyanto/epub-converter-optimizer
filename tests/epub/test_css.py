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
        ".c { display:inline-grid;color:blue }\n"
        ".d { display: block; -webkit-columns: 2; column-count: 3 }\n"
        ".e { position: absolute; top: 0 }\n"
        "@media screen and (max-width: 100px) { p { color: green; float: none } }\n"
    )
    assert rewrite_css(css, keep, xteink=True) == (
        ".a {  width: 40% }\n"
        ".b {  justify-content: center }\n"
        ".c { color:blue }\n"
        ".d { display: block;  }\n"
        ".e {  top: 0 }\n"
        "@media screen and (max-width: 100px) { p { color: green; } }\n"
    )


def test_general_keeps_every_declaration():
    css = ".a { float: left; display: flex; position: absolute; columns: 2 }"
    assert rewrite_css(css, keep) == css


def test_xteink_drops_font_faces_and_comments_but_not_strings():
    css = (
        "/* float: left; */\n@font-face { font-family: F; src: url(f.otf) }\n"
        'p::before { content: "}; float: x"; color: red }'
    )
    out = rewrite_css(css, keep, xteink=True)
    assert "@font-face" not in out and "/*" not in out
    assert 'content: "}; float: x"; color: red' in out


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
    css = ".a { background: url(data:image/png;base64,AAAA;BBB); margin: 0 }"
    seen = []

    def spy(ref):
        seen.append(ref)
        return ref

    assert rewrite_css(css, spy, xteink=True) == css
    assert seen == ["data:image/png;base64,AAAA;BBB"]


def test_a_style_attribute_is_just_a_declaration_list():
    assert rewrite_css("float:left;color:#222", keep, xteink=True) == "color:#222"
    assert rewrite_css("color:#222;float:left", keep, xteink=True) == "color:#222;"
    assert rewrite_css("float:left", keep, xteink=True) == ""
