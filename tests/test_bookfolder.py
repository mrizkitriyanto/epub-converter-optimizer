from eco.book import Block, Book
from eco.bookfolder import load_source, read_report, write_book
from eco.events import Finding


def test_round_trip(tmp_path):
    book = Book(
        title='T: "x"',
        language="id",
        blocks=[
            Block("heading", "Bab 1", level=1, page=3),
            Block("paragraph", "*bukan* #judul", page=3),
            Block("code", "a\n    b", page=4),
            Block(
                "table",
                html="<table><tr><td>1</td></tr></table>",
                image="images/p0004-table-1.png",
                page=4,
            ),
        ],
    )
    md = write_book(book, tmp_path / "b.book", []).read_text()
    assert "<!-- page: 3 -->" in md and "<!-- page: 4 -->" in md
    assert "\\*bukan\\* \\#judul" in md
    assert "```\na\n    b\n```" in md
    assert "<!-- table-image: images/p0004-table-1.png -->" in md
    src = load_source(tmp_path / "b.book")
    assert src.meta["title"] == 'T: "x"' and src.meta["language"] == "id"
    assert src.base_dir == tmp_path / "b.book"
    assert src.markdown.startswith("<!-- page: 3 -->")


def test_write_book_returns_book_md_and_creates_folder(tmp_path):
    folder = tmp_path / "deep" / "b.book"
    assert write_book(Book(title="T"), folder, []) == folder / "book.md"
    assert (folder / "report.json").is_file()


def test_page_marker_only_on_change(tmp_path):
    blocks = [Block("paragraph", "a", page=2), Block("paragraph", "b", page=2)]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    assert md.count("<!-- page: 2 -->") == 1
    blocks = [Block("paragraph", "a"), Block("paragraph", "b")]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    assert "<!-- page" not in md


def test_hand_written_front_matter_with_plain_scalars(tmp_path):
    md = tmp_path / "x.md"
    md.write_text('---\ntitle: My Book: Part 1\nauthor: "Jane"\n---\n# Hi\n')
    src = load_source(md)
    assert src.meta == {"title": "My Book: Part 1", "author": "Jane"}
    assert src.markdown == "# Hi\n"
    assert src.base_dir == tmp_path


def test_missing_front_matter_uses_stem(tmp_path):
    (tmp_path / "x.md").write_text("# Hi\n")
    assert load_source(tmp_path / "x.md").meta == {"title": "x"}
    (tmp_path / "y.book").mkdir()
    (tmp_path / "y.book" / "book.md").write_text("text\n")
    src = load_source(tmp_path / "y.book")
    assert src.meta == {"title": "y"} and src.markdown == "text\n"


def test_escaping_keeps_pdf_text_from_becoming_markup(tmp_path):
    blocks = [
        Block("paragraph", "a <b>x</b> & c | d `e` _f_ [g]", page=1),
        Block("paragraph", "1. not a list\n- nor this\n+ or this", page=1),
        Block("list_item", "one *two*", page=1),
        Block("list_item", "three", page=1),
        Block("heading", "A # B", level=2, page=1),
    ]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    assert "a \\<b\\>x\\</b\\> \\& c \\| d \\`e\\` \\_f\\_ \\[g\\]" in md
    assert "1\\. not a list\n\\- nor this\n\\+ or this" in md
    assert "- one \\*two\\*\n- three" in md
    assert "## A \\# B" in md


def test_code_fence_choice(tmp_path):
    def code(text):
        blocks = [Block("code", text)]
        return write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()

    assert "~~~\n```\n~~~" in code("```")
    assert "````\n```\n~~~\n````" in code("```\n~~~")


def test_image_and_figure(tmp_path):
    blocks = [
        Block("image", "A *dog*", image="images/p0001-img-1.png", page=1),
        Block("picture", "Dog & cat", image="images/p0001-img-2.png", caption="Fig <1>", page=1),
        Block("picture", "no image here", page=1),
    ]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    assert "![A \\*dog\\*](images/p0001-img-1.png)" in md
    assert (
        '<figure><img src="images/p0001-img-2.png" alt="Dog &amp; cat"/>'
        "<figcaption>Fig &lt;1&gt;</figcaption></figure>"
    ) in md
    assert "\nno image here\n" in md


def test_table_html_has_no_blank_lines(tmp_path):
    html = "<table>\n\n<tr><td>1</td></tr>\n\n</table>"
    blocks = [Block("table", html=html, image="images/t.png", page=1)]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    assert "<!-- table-image: images/t.png -->\n<table>\n<tr><td>1</td></tr>\n</table>" in md


def test_footnotes_go_before_next_heading_of_same_or_higher_level(tmp_path):
    blocks = [
        Block("heading", "A", level=1, page=1),
        Block("footnote", "fn <A>", page=1),
        Block("paragraph", "text A", page=1),
        Block("heading", "A.1", level=2, page=1),
        Block("footnote", "fn A.1", page=1),
        Block("heading", "A.2", level=2, page=2),
        Block("heading", "B", level=1, page=2),
        Block("footnote", "fn B", page=2),
    ]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    order = [
        "# A\n",
        "text A",
        "## A.1",
        '<p class="footnote">fn A.1</p>',
        "## A.2",
        '<p class="footnote">fn &lt;A&gt;</p>',
        "# B\n",
        '<p class="footnote">fn B</p>',
    ]
    positions = [md.index(s) for s in order]
    assert positions == sorted(positions)


def test_report_round_trip(tmp_path):
    findings = [Finding(3, "ocr", "warning", "low confidence"), Finding(0, "info", "info", "ü")]
    write_book(Book(title="T"), tmp_path, findings)
    assert read_report(tmp_path) == findings
