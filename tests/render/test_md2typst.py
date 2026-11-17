import json
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
import typst
from PIL import Image
from pypdf import PdfReader

from eco.bookfolder import load_source
from eco.options import Options, image_profile
from eco.render.md2typst import VIEWS, RenderSettings, to_typst


def convert(tmp_path, markdown, *, device="x4", view="crosspoint", settings=None, profile=None):
    md = tmp_path / "b.md"
    md.write_text(markdown, encoding="utf-8")
    files = to_typst(
        load_source(md),
        device=device,
        settings=settings or RenderSettings(),
        view=view,
        image_profile=profile,
    )
    return files["main.typ"].decode(), files


def _materialise(files, folder: Path) -> Path:
    """typst-py takes no binary files in a dict, so the page renderer writes the folder first."""
    for name, data in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.read_bytes() if isinstance(data, Path) else data)
    return folder / "main.typ"


def compiles(files) -> int:
    """Compile the way the page renderer does; returns the number of pages."""
    with tempfile.TemporaryDirectory() as folder:
        main = _materialise(files, Path(folder))
        pages = typst.compile(main, root=folder, format="png", ppi=72.0, ignore_system_fonts=True)
    return len(pages) if isinstance(pages, list) else 1


def page_text(files) -> str:
    with tempfile.TemporaryDirectory() as folder:
        main = _materialise(files, Path(folder))
        pdf = typst.compile(main, root=folder, format="pdf", ignore_system_fonts=True)
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)


def query(files, selector: str, field: str):
    with tempfile.TemporaryDirectory() as folder:
        main = _materialise(files, Path(folder))
        result = typst.query(
            main, selector, field=field, format="json", root=folder, ignore_system_fonts=True
        )
    return json.loads(result)


def test_escaping_and_markers(tmp_path):
    md = tmp_path / "b.md"
    md.write_text("# Bab #1\n\n<!-- page: 7 -->\n\nHarga $5 *murah*\n")
    main = to_typst(load_source(md), device="x4", settings=RenderSettings(), view="crosspoint")[
        "main.typ"
    ].decode()
    assert "= Bab \\#1" in main and "Harga \\$5 _murah_" in main
    assert "(src: 7, page: here().page())" in main and "<srcpage>" in main and "<chap>" in main


def test_stock_view_hides_images(tmp_path, small_book):
    main = to_typst(load_source(small_book), device="x4", settings=RenderSettings(), view="stock")[
        "main.typ"
    ].decode()
    assert "image(" not in main and "Image not shown on stock firmware" in main


def test_views():
    assert VIEWS == ("crosspoint", "crossink", "stock", "xtc")


def test_unknown_device_and_view_are_refused(tmp_path):
    with pytest.raises(ValueError, match="device"):
        convert(tmp_path, "x", device="nope")
    with pytest.raises(ValueError, match="view"):
        convert(tmp_path, "x", view="nope")


def test_crossink_renders_like_crosspoint(tmp_path, small_book):
    def main(view):
        return to_typst(load_source(small_book), device="x4", settings=RenderSettings(), view=view)[
            "main.typ"
        ]

    assert main("crossink") == main("crosspoint")


def test_preamble_follows_device_and_settings(tmp_path):
    main, _ = convert(tmp_path, "---\nlanguage: id\n---\nText\n", device="x3")
    assert "width: 528pt, height: 792pt" in main
    assert 'lang: "id"' in main and 'font: "Libertinus Serif"' in main and "size: 32pt" in main
    assert "justify: true, leading: 0.35em" in main
    assert 'font: "DejaVu Sans Mono", size: 0.62em' in main
    assert "bottom: 38pt" in main
    assert "counter(page).final()" in main
    general, _ = convert(tmp_path, "Text\n", device="general")
    assert "width: 480pt, height: 800pt" in general and 'lang: "en"' in general
    custom, _ = convert(
        tmp_path,
        "Text\n",
        settings=RenderSettings(font_size=20, margin=10, line_height=1.5, status_bar=False),
    )
    assert "size: 20pt" in custom and "bottom: 32pt" in custom and "leading: 0.5em" in custom
    assert "footer" not in custom


def test_language_that_typst_would_refuse_falls_back(tmp_path):
    main, _ = convert(tmp_path, "---\nlanguage: en-US\n---\nText\n")
    assert 'lang: "en"' in main
    main, _ = convert(tmp_path, "---\nlanguage: not a code\n---\nText\n")
    assert 'lang: "en"' in main


def test_headings_start_pages_and_carry_markers(tmp_path):
    main, files = convert(tmp_path, "# One\n\ntext\n\n## Sub\n\n### Deep\n\n# Two\n")
    assert "#show heading.where(level: 1): it => { pagebreak(weak: true); it }" in main
    assert "\n== Sub\n" in main and "\n=== Deep\n" in main
    assert main.count("page: here().page())) <chap>]") == 2  # level 1 only
    assert '(title: "One", page: here().page())' in main
    # The marker sits after an explicit break, so it reports the chapter's own first page.
    assert '#pagebreak(weak: true)\n#context [#metadata((title: "One"' in main
    assert compiles(files) == 2


def test_chapter_marker_reports_the_first_page_of_the_chapter(tmp_path):
    _, files = convert(tmp_path, "intro\n\n# One\n\ntext\n\n# Two\n\ntext\n")
    marks = query(files, "<chap>", "value")
    assert [m["page"] for m in marks] == [2, 3]


def test_page_marker_before_a_chapter_heading_follows_the_chapter_break(tmp_path):
    main, files = convert(
        tmp_path, "<!-- page: 1 -->\n\n# One\n\ntext\n\n<!-- page: 2 -->\n\n# Two\n"
    )
    assert main.count("#pagebreak(weak: true)\n#context [#metadata((title:") == 2
    assert '"Two", page: here().page())) <chap>]\n#context [#metadata((src: 2,' in main
    marks = query(files, "<srcpage>", "value")
    assert [(m["src"], m["page"]) for m in marks] == [(1, 1), (2, 2)]


def test_marker_before_a_nested_heading_stays_where_it_is(tmp_path):
    main, _ = convert(tmp_path, "<!-- page: 2 -->\n\n> # Quoted\n")
    assert main.index("(src: 2,") < main.index("Quoted")
    assert main.count("<chap>]") == 0


def test_long_raw_lines_wrap_inside_the_page(tmp_path):
    main, files = convert(tmp_path, "# C\n\n```\n" + "x" * 160 + "\n```\n")
    assert "sym.zws" in main
    assert compiles(files) == 1


def test_marker_title_is_a_safe_string(tmp_path):
    main, files = convert(tmp_path, '# Say "hi" \\ *bold* `code`\n')
    assert '(title: "Say \\"hi\\" \\\\ bold code"' in main
    assert compiles(files) == 1


def test_inline_markup_and_code(tmp_path):
    main, files = convert(
        tmp_path,
        'A *b* **c** `d "q" \\ e` f.\n\n```\nline "1"\n  line 2\n```\n\n'
        "un*believ*able and **Ünï**code\n",
    )
    assert "_b_ *c*" in main
    assert '#raw("d \\"q\\" \\\\ e");' in main
    assert '#raw(block: true, "line \\"1\\"\\n  line 2")' in main
    assert "un#emph[believ];able" in main and "#strong[Ünï];code" in main
    assert compiles(files) == 1


def test_text_is_escaped(tmp_path):
    main, files = convert(
        tmp_path,
        r"x \\ # $ \* \_ \` < > @ \[ \] ~ // a -- b --- c -? d" "\n",
    )
    body = main.split("\n\n")[-1]
    for special in ("\\\\", "\\#", "\\$", "\\*", "\\_", "\\`", "\\<", "\\>", "\\@", "\\[", "\\]"):
        assert special in body
    assert "\\~" in body and "\\/\\/" in body
    assert "a \\-- b" in body and "\\-\\-- c" in body and "\\-? d" in body
    assert compiles(files) == 1


def test_line_start_markup_stays_text(tmp_path):
    source = (
        "1\\. Introduction\n\n"
        "\\- not a bullet\n\n"
        "\\+ not a number\n\n"
        "\\= not a heading\n\n"
        "/ not: a term\n\n"
        "2\\) kept\n\n"
        "line one\\\n10\\. after a break\n\n"
        "- 3\\. inside an item\n"
    )
    main, files = convert(tmp_path, source)
    assert "1\\. Introduction" in main
    assert "\\- not a bullet" in main and "\\+ not a number" in main
    assert "\\= not a heading" in main and "\\/ not: a term" in main
    assert "2) kept" in main
    assert "\\\n10\\. after a break" in main
    assert "- 3\\. inside an item" in main
    # A real bullet is still a list: nothing but the last item became one.
    assert main.count("\n- ") == 1 and "\n+ " not in main
    assert compiles(files) == 1
    # Typst itself sees one list item and no enum, term or heading.
    probe = (
        "#show list.item: [LISTITEM]\n#show enum.item: [ENUMITEM]\n"
        "#show terms.item: [TERMITEM]\n#show heading: [HEADING]\n"
    )
    probed = {**files, "main.typ": probe.encode() + files["main.typ"]}
    text = page_text(probed)
    assert text.count("LISTITEM") == 1
    assert not {"ENUMITEM", "TERMITEM", "HEADING"} & set(text.split())
    assert "1. Introduction" in text and "= not a heading" in text and "/ not: a term" in text


def test_line_start_markup_in_a_table_cell_stays_text(tmp_path):
    main, files = convert(
        tmp_path,
        "<table><tr><td>1. x</td><td>- y</td></tr></table>\n",
    )
    assert "[1\\. x]" in main and "[\\- y]" in main
    assert compiles(files) == 1


def test_lists_and_quotes_compile(tmp_path):
    main, files = convert(
        tmp_path,
        "- a\n- b\n  - nested\n\n3. three\n4. four\n\n> quoted *text*\n\n---\n\n"
        "text[^1]\n\n[^1]: A note.\n\n[link *me*](http://x.test/a_b)\n",
    )
    assert "\n- a\n- b\n  - nested" in main
    assert "\n3. three\n4. four" in main
    assert "quoted _text_" in main
    assert "link _me_" in main and "x.test" not in main
    assert "#super[1];" in main
    assert compiles(files) == 1


def test_hard_and_soft_breaks(tmp_path):
    main, files = convert(tmp_path, "one\ntwo  \nthree<br>four\n")
    assert "one two \\\nthree \\\nfour" in main
    assert compiles(files) == 1


def test_images_become_figures_and_ship_with_the_source(tmp_path, small_book):
    src = load_source(small_book)
    files = to_typst(src, device="x4", settings=RenderSettings(), view="crosspoint")
    main = files["main.typ"].decode()
    assert (
        '#figure(image("images/p0001-img-1.png", width: 80pt, height: 60pt, fit: "contain"), '
        "caption: [A picture]);" in main
    )
    shipped = files["images/p0001-img-1.png"]
    assert isinstance(shipped, Path)
    assert shipped.resolve() == (small_book / "images" / "p0001-img-1.png").resolve()
    assert compiles(files) == 2


def test_image_profile_transforms_the_files(tmp_path, small_book):
    profile = image_profile(Options(device="x4", size="small"))
    src = load_source(small_book)
    files = to_typst(
        src, device="x4", settings=RenderSettings(), view="crosspoint", image_profile=profile
    )
    data = files["images/p0001-img-1.png"]
    assert isinstance(data, bytes) and data.startswith(b"\x89PNG")
    assert compiles(files) == 2


def test_image_profile_that_drops_images_leaves_no_figure(tmp_path, small_book):
    profile = image_profile(Options(device="x4", size="small", firmware="stock"))
    files = to_typst(
        load_source(small_book),
        device="x4",
        settings=RenderSettings(),
        view="crosspoint",
        image_profile=profile,
    )
    assert "image(" not in files["main.typ"].decode() and len(files) == 1


def test_converted_image_keeps_a_matching_extension(tmp_path):
    folder = tmp_path / "book"
    folder.mkdir()
    Image.new("RGB", (60, 40), "red").save(folder / "photo.gif")
    (folder / "b.md").write_text("![](photo.gif)\n")
    profile = image_profile(Options(device="general", size="small"))
    files = to_typst(
        load_source(folder / "b.md"),
        device="general",
        settings=RenderSettings(),
        view="crosspoint",
        image_profile=profile,
    )
    names = [name for name in files if name != "main.typ"]
    assert len(names) == 1 and names[0].startswith("photo") and names[0] != "photo.gif"
    assert f'image("{names[0]}"' in files["main.typ"].decode()
    assert "caption: [" not in files["main.typ"].decode()
    assert compiles(files) == 1


def test_missing_and_outside_images_are_left_out(tmp_path):
    secret = tmp_path / "secret.png"
    Image.new("L", (40, 40)).save(secret)
    folder = tmp_path / "book"
    folder.mkdir()
    (folder / "b.md").write_text(
        "![gone](missing.png)\n\n![out](../secret.png)\n\n![web](http://x.test/a.png)\n\nafter\n"
    )
    files = to_typst(
        load_source(folder / "b.md"), device="x4", settings=RenderSettings(), view="crosspoint"
    )
    assert "image(" not in files["main.typ"].decode() and len(files) == 1
    assert "after" in files["main.typ"].decode()
    assert compiles(files) == 1


def test_captioned_figure_html_from_the_book_folder(tmp_path):
    folder = tmp_path / "book"
    (folder / "images").mkdir(parents=True)
    Image.new("L", (40, 30)).save(folder / "images" / "a.png")
    (folder / "b.md").write_text(
        '<figure><img src="images/a.png" alt="alt text"/><figcaption>The caption</figcaption>'
        "</figure>\n"
    )
    files = to_typst(
        load_source(folder / "b.md"), device="x4", settings=RenderSettings(), view="crosspoint"
    )
    assert "caption: [The caption]" in files["main.typ"].decode()
    assert "images/a.png" in files
    assert compiles(files) == 1


def test_small_table_is_a_typst_table(tmp_path):
    main, files = convert(
        tmp_path,
        "<table>\n<tr><th>Name</th><th>Qty</th></tr>\n<tr><td>a &amp; b</td><td>$5</td></tr>\n"
        "</table>\n",
    )
    assert "#table(\n  columns: 2," in main
    assert "[#strong[Name]]" in main and "[a & b]" in main and "[\\$5]" in main
    assert compiles(files) == 1


def test_pipe_table_is_a_typst_table(tmp_path):
    main, files = convert(tmp_path, "| a | b |\n|---|---|\n| 1 | *2* |\n")
    assert "columns: 2" in main and "[#strong[a]]" in main
    assert compiles(files) == 1


def test_wide_table_uses_its_image_twin_on_xteink_only(tmp_path, small_book):
    src = load_source(small_book)
    xteink = to_typst(src, device="x4", settings=RenderSettings(), view="crosspoint")
    main = xteink["main.typ"].decode()
    assert "#table(" not in main
    assert 'image("images/p0002-table-1.png", width: 240pt, height: 90pt, fit: "contain")' in main
    assert "images/p0002-table-1.png" in xteink
    general = to_typst(src, device="general", settings=RenderSettings(), view="crosspoint")
    assert "#table(\n  columns: 6," in general["main.typ"].decode()
    assert "images/p0002-table-1.png" not in general
    assert compiles(xteink) == 2 and compiles(general) == 2


def test_spanned_table_uses_its_twin_even_on_general(tmp_path):
    folder = tmp_path / "book"
    folder.mkdir()
    Image.new("L", (60, 40)).save(folder / "t.png")
    table = '<table><tr><td colspan="2">wide</td></tr><tr><td>a</td><td>b</td></tr></table>'
    (folder / "b.md").write_text(f"<!-- table-image: t.png -->\n{table}\n")
    src = load_source(folder / "b.md")
    main = to_typst(src, device="general", settings=RenderSettings(), view="crosspoint")["main.typ"]
    assert b"#table(" not in main and b'image("t.png"' in main


def test_spanned_table_without_twin_keeps_the_spans(tmp_path):
    main, files = convert(
        tmp_path,
        '<table><tr><td colspan="2">wide</td></tr><tr><td rowspan="2">a</td><td>b</td></tr>'
        "<tr><td>c</td></tr></table>\n",
    )
    assert "table.cell(colspan: 2)[wide]" in main and "table.cell(rowspan: 2)[a]" in main
    assert compiles(files) == 1


def test_stock_view_boxes_the_table_twin_too(tmp_path, small_book):
    main = to_typst(load_source(small_book), device="x4", settings=RenderSettings(), view="stock")[
        "main.typ"
    ].decode()
    assert main.count("Image not shown on stock firmware") == 2  # picture and table twin
    assert "#rect(width: 100%, stroke: 1pt + gray)[Image not shown on stock firmware]" in main


def test_whole_small_book_compiles_with_footer(tmp_path, small_book):
    files = to_typst(
        load_source(small_book), device="x4", settings=RenderSettings(), view="crosspoint"
    )
    assert compiles(files) == 2
    marks = query(files, "<chap>", "value")
    assert [m["title"] for m in marks] == ["One", "Two"]


def test_page_comments_are_dropped_and_other_html_is_text(tmp_path):
    main, files = convert(
        tmp_path,
        '<!-- page: 3 -->\n\n<!-- remark -->\n\n<p class="footnote">Note <b>one</b> &amp; two</p>\n',
    )
    assert "remark" not in main and "Note one & two" in main
    assert "(src: 3," in main
    assert compiles(files) == 1


def test_table_without_cells_is_left_out(tmp_path):
    main, files = convert(tmp_path, "<table><tr></tr></table>\n\nafter\n")
    assert "#table(" not in main and "after" in main
    assert compiles(files) == 1


def probed_text(files) -> str:
    """The page text with each list, enum, term and heading replaced by a marker word."""
    probe = (
        "#show list.item: [LISTITEM]\n#show enum.item: [ENUMITEM]\n"
        "#show terms.item: [TERMITEM]\n#show heading: [HEADING]\n"
    )
    return page_text({**files, "main.typ": probe.encode() + files["main.typ"]})


def figure_extent(files) -> dict:
    """Page and bottom edge of the first figure (image, gap and caption), from Typst itself."""
    probe = (
        "\n#context [#metadata((page: query(figure).first().location().position().page, "
        "bottom: query(figure).first().location().position().y.pt()"
        " + measure(width: 448pt, query(figure).first()).height.pt())) <probe>]\n"
    )
    probed = {**files, "main.typ": files["main.typ"] + probe.encode()}
    return query(probed, "<probe>", "value")[0]


# Fix round 1


def test_level_one_heading_in_a_container_is_an_ordinary_heading(tmp_path):
    main, files = convert(
        tmp_path, "> # Quoted heading\n\n- # Heading in item\n\n# Top\n\ntext\n\n1. # Numbered\n"
    )
    assert main.count("page: here().page())) <chap>]") == 1  # only the top-level heading
    assert "== Quoted heading" in main and "- == Heading in item" in main
    assert "1. == Numbered" in main
    assert compiles(files) == 2  # the top-level heading still starts its own page
    text = page_text(files)
    for words in ("Quoted heading", "Heading in item", "Numbered", "Top"):
        assert words in text
    marks = query(files, "<chap>", "value")
    assert [m["title"] for m in marks] == ["Top"] and marks[0]["page"] == 2


def test_tall_image_keeps_its_caption_on_the_page(tmp_path):
    Image.new("L", (100, 1000), 120).save(tmp_path / "tall.png")
    main, files = convert(tmp_path, "![A tall picture](tall.png)\n")
    # The body is 448 x 746 (480 x 800 minus margins and the footer). The image leaves room for
    # the caption and the gap, so it is scaled down instead of pushing the caption out.
    assert 'image("tall.png", width: 6' in main and "height: 6" in main
    assert compiles(files) == 1
    extent = figure_extent(files)
    assert extent["page"] == 1
    assert extent["bottom"] <= 800 - 38  # the caption ends above the footer


def test_long_caption_gets_more_room_than_a_short_one(tmp_path):
    Image.new("L", (100, 1000), 120).save(tmp_path / "tall.png")
    short, _ = convert(tmp_path, "![Short](tall.png)\n")
    caption = " ".join(["word"] * 40)
    long, files = convert(tmp_path, f"![{caption}](tall.png)\n")

    def height(main):
        return float(main.split('image("tall.png"')[1].split("height: ")[1].split("pt")[0])

    assert height(long) < height(short)
    assert compiles(files) == 1
    extent = figure_extent(files)
    assert extent["page"] == 1 and extent["bottom"] <= 800 - 38


def test_small_image_keeps_its_natural_size(tmp_path):
    Image.new("L", (40, 30), 120).save(tmp_path / "formula.png")
    main, files = convert(tmp_path, "![](formula.png)\n")
    assert 'image("formula.png", width: 40pt, height: 30pt, fit: "contain")' in main
    assert compiles(files) == 1


def test_wide_image_is_limited_to_the_body_width(tmp_path):
    Image.new("L", (2000, 100), 120).save(tmp_path / "wide.png")
    main, files = convert(tmp_path, "![](wide.png)\n")
    assert 'image("wide.png", width: 448pt, height: 22.4pt, fit: "contain")' in main
    main, files = convert(tmp_path, "![](wide.png)\n", device="x3")
    assert "width: 496pt, height: 24.8pt" in main  # 528 - 2 * 16
    assert compiles(files) == 1


def test_image_sizing_follows_the_settings(tmp_path):
    Image.new("L", (1000, 1000), 120).save(tmp_path / "big.png")
    settings = RenderSettings(margin=40)
    main, files = convert(tmp_path, "![](big.png)\n", settings=settings)
    assert "width: 400pt, height: 400pt" in main  # 480 - 2 * 40
    assert compiles(files) == 1


def test_vector_image_is_capped_in_height_and_compiles(tmp_path):
    (tmp_path / "v.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        '<rect width="20" height="20"/></svg>'
    )
    main, files = convert(tmp_path, "![v](v.svg)\n")
    assert 'image("v.svg", width: 100%, height: ' in main
    assert compiles(files) == 1


def test_html_block_text_is_kept_next_to_an_image(tmp_path):
    Image.new("L", (60, 40), 120).save(tmp_path / "logo.png")
    main, files = convert(
        tmp_path,
        '<p align="center"><img src="logo.png"><br>Caption text that matters</p>\n',
    )
    assert 'image("logo.png"' in main
    assert main.index('image("logo.png"') < main.index("Caption text that matters")
    assert "Caption text that matters" in page_text(files)


def test_html_block_text_is_kept_next_to_a_table_and_follows_the_line_start_rule(tmp_path):
    main, files = convert(
        tmp_path,
        "<table><tr><td>a</td></tr></table>\n1. After the table\n",
    )
    assert "#table(" in main and "1\\. After the table" in main
    assert compiles(files) == 1


def test_break_followed_by_a_space_keeps_the_line_start_rule(tmp_path):
    main, files = convert(tmp_path, "three<br> - four<br> 5. five<br> + six<br> = seven\n")
    for escaped in ("\\- four", "\\+ six", "\\= seven", "5\\. five"):
        assert escaped in main
    text = probed_text(files)
    assert not {"LISTITEM", "ENUMITEM", "TERMITEM", "HEADING"} & set(text.split())
    assert "5. five" in text and "- four" in text


def test_text_after_a_dropped_leading_image_follows_the_line_start_rule(tmp_path):
    main, files = convert(
        tmp_path,
        "![gone](missing.png) 1. five\n\n![](missing.png)- dash\n\n![](missing.png)<br> 2. two\n",
    )
    assert "\n1\\. five" in main and "\n\\- dash" in main and "2\\. two" in main
    text = probed_text(files)
    assert not {"LISTITEM", "ENUMITEM"} & set(text.split())


def write_bad_images(folder: Path) -> None:
    (folder / "garbage.png").write_bytes(b"this is not a png")
    good = BytesIO()
    Image.effect_noise((200, 200), 80).save(good, "PNG")
    (folder / "cut.png").write_bytes(good.getvalue()[: len(good.getvalue()) // 2])
    (folder / "broken.svg").write_text("<svg><rect></svg")
    (folder / "empty.jpg").write_bytes(b"")


BAD_IMAGES = "![a](garbage.png)\n\n![b](cut.png)\n\n![c](broken.svg)\n\n![d](empty.jpg)\n\nafter\n"


def test_damaged_images_are_left_out_without_a_profile(tmp_path):
    write_bad_images(tmp_path)
    main, files = convert(tmp_path, BAD_IMAGES)
    assert "image(" not in main and len(files) == 1 and "after" in main
    assert compiles(files) == 1


def test_damaged_images_are_left_out_with_a_profile(tmp_path):
    write_bad_images(tmp_path)
    profile = image_profile(Options(device="x4", size="balanced"))
    main, files = convert(tmp_path, BAD_IMAGES, profile=profile)
    assert "image(" not in main and len(files) == 1 and "after" in main
    assert compiles(files) == 1


@pytest.mark.parametrize("use_profile", [False, True])
def test_decompression_bomb_is_left_out(tmp_path, monkeypatch, use_profile):
    Image.new("L", (60, 60), 120).save(tmp_path / "bomb.png")
    Image.new("L", (30, 30), 120).save(tmp_path / "fine.png")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # over twice this raises an error
    profile = image_profile(Options(device="x4")) if use_profile else None
    main, files = convert(tmp_path, "![](bomb.png)\n\n![](fine.png)\n", profile=profile)
    assert 'image("bomb.png"' not in main and "fine.png" in main
    assert compiles(files) == 1


def test_unreadable_table_twin_falls_back_to_the_table(tmp_path):
    (tmp_path / "t.png").write_bytes(b"garbage")
    table = "<tr>" + "<td>x</td>" * 6 + "</tr>"
    main, files = convert(tmp_path, f"<!-- table-image: t.png -->\n<table>{table}</table>\n")
    assert "#table(\n  columns: 6," in main and "image(" not in main
    assert compiles(files) == 1


# Fix round 2

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="9" height="9"/></svg>'


def test_image_whose_suffix_does_not_match_its_format_is_renamed(tmp_path):
    Image.new("RGB", (60, 40), "red").save(tmp_path / "photo.png", "JPEG")  # a JPEG named .png
    Image.new("L", (30, 20), 120).save(tmp_path / "plain.png")
    Image.new("L", (30, 20), 120).save(tmp_path / "shot.jpeg", "PNG")  # a PNG named .jpeg
    Image.new("L", (30, 20), 90).save(tmp_path / "photo.jpg", "JPEG")  # the name a rename wants
    main, files = convert(
        tmp_path, "![](photo.png)\n\n![](plain.png)\n\n![](shot.jpeg)\n\n![](photo.jpg)\n"
    )
    # The JPEG named .png is met first and takes photo.jpg; the real photo.jpg then gets -2.
    assert 'image("photo.jpg", width: 60pt' in main
    assert 'image("photo-2.jpg", width: 30pt' in main
    assert 'image("shot.png", width: 30pt' in main and 'image("plain.png"' in main
    assert files["photo.jpg"] == (tmp_path / "photo.png").read_bytes()
    assert files["photo-2.jpg"].resolve() == (tmp_path / "photo.jpg").resolve()
    assert isinstance(files["plain.png"], Path)  # matching files are still passed as they are
    assert compiles(files) == 1


def test_jpeg_named_png_keeps_its_good_neighbours(tmp_path):
    Image.new("RGB", (60, 40), "red").save(tmp_path / "photo.png", "JPEG")
    Image.new("L", (30, 20), 120).save(tmp_path / "ok.png")
    main, files = convert(tmp_path, "![](photo.png)\n\n![](ok.png)\n\nafter\n")
    assert main.count("#figure(") == 2 and "after" in main
    assert compiles(files) == 1


def test_svg_with_a_foreign_root_is_left_out_and_real_svgs_stay(tmp_path):
    (tmp_path / "page.svg").write_text("<html/>")
    (tmp_path / "other.svg").write_text('<svg xmlns="http://x.test/"/>')
    (tmp_path / "good.svg").write_text(SVG)
    (tmp_path / "bare.svg").write_text(
        '<svg width="20" height="20"><rect width="9" height="9"/></svg>'
    )
    main, files = convert(
        tmp_path, "![a](page.svg)\n\n![b](other.svg)\n\n![c](good.svg)\n\n![d](bare.svg)\n\nafter\n"
    )
    assert 'image("page.svg"' not in main and 'image("other.svg"' not in main
    assert 'image("good.svg"' in main and 'image("bare.svg"' in main and "after" in main
    assert compiles(files) >= 1  # vector images fill the body width, so the page count varies


def test_image_in_a_format_typst_cannot_read_is_left_out(tmp_path):
    Image.new("RGB", (30, 20), "red").save(tmp_path / "scan.png", "BMP")  # a BMP named .png
    main, files = convert(tmp_path, "![](scan.png)\n\nafter\n")
    assert "image(" not in main and len(files) == 1
    assert compiles(files) == 1


# Fix round 3


def save_mpo(path: Path) -> None:
    """A multi-picture JPEG (phone photos with depth or gain-map data), which PIL reports as MPO."""
    first = Image.new("RGB", (60, 40), "red")
    first.save(path, "MPO", save_all=True, append_images=[Image.new("RGB", (60, 40), "blue")])
    with Image.open(path) as im:
        assert im.format == "MPO"


@pytest.mark.parametrize("name", ["mpo.jpg", "mpo.jpeg"])
def test_multi_picture_jpeg_is_kept_as_it_is(tmp_path, name):
    save_mpo(tmp_path / name)
    main, files = convert(tmp_path, f"![]({name})\n\nafter\n")
    assert f'image("{name}", width: 60pt, height: 40pt' in main
    assert isinstance(files[name], Path)  # passed unchanged, not renamed
    assert compiles(files) == 1


def test_multi_picture_jpeg_named_png_is_renamed_to_jpg(tmp_path):
    save_mpo(tmp_path / "mpo.png")
    main, files = convert(tmp_path, "![](mpo.png)\n")
    assert 'image("mpo.jpg", width: 60pt' in main and "mpo.png" not in files
    assert compiles(files) == 1


@pytest.mark.parametrize("device", ["x4", "general"])
def test_multi_picture_jpeg_goes_through_the_profile(tmp_path, device):
    save_mpo(tmp_path / "mpo.jpg")
    profile = image_profile(Options(device=device))
    main, files = convert(tmp_path, "![](mpo.jpg)\n", device=device, profile=profile)
    names = [name for name in files if name != "main.typ"]
    assert len(names) == 1 and names[0].startswith("mpo.") and f'image("{names[0]}"' in main
    assert isinstance(files[names[0]], bytes)  # re-encoded: the first picture only
    assert compiles(files) == 1
