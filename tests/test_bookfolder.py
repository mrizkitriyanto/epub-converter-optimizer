import sys
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from eco.book import Block, Book
from eco.bookfolder import RemovedByAntivirus, load_source, read_report, write_book
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


@pytest.mark.parametrize(
    "numbers, markdown, lists",
    [
        ([3, 4, 5], "3. x\n4. x\n5. x", [(3, 3)]),
        ([1, 2, 1, 2, 3], "1. x\n2. x\n1) x\n2) x\n3) x", [(1, 2), (1, 3)]),  # starts again
        ([5, 7], "5. x\n7) x", [(5, 1), (7, 1)]),  # a number skipped
        ([0, 1], "0. x\n1. x", [(0, 2)]),  # a list that starts at 0
        ([2, 1, 2, 9], "2. x\n1) x\n2) x\n9. x", [(2, 1), (1, 2), (9, 1)]),
    ],
)
def test_a_numbered_item_that_does_not_follow_on_starts_a_new_list(
    tmp_path, numbers, markdown, lists
):
    """book.md is plain CommonMark: any renderer shows each item with its own number."""
    blocks = [Block("list_item", "x", number=n, page=1) for n in numbers]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    assert markdown in md
    found = []  # (start, number of items) of each ordered list
    for token in MarkdownIt("commonmark").parse(load_source(tmp_path).markdown):
        if token.type == "ordered_list_open":
            found.append((token.attrs.get("start", 1), 0))
        elif token.type == "list_item_open":
            found[-1] = (found[-1][0], found[-1][1] + 1)
    assert found == lists


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


def test_preamble_footnote_goes_before_first_heading(tmp_path):
    blocks = [
        Block("paragraph", "preface", page=1),
        Block("footnote", "fn preface", page=1),
        Block("heading", "Ch 1", level=1, page=2),
        Block("heading", "Ch 2", level=1, page=3),
    ]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    assert md.index("fn preface") < md.index("# Ch 1") < md.index("# Ch 2")


def test_blocks_with_an_image_are_written_as_images(tmp_path):
    blocks = [
        Block("formula", "E = mc^2", image="images/p0001-formula-1.png", page=1),
        Block("formula", image="images/p0001-formula-2.png", page=1),
        Block("code", "x = 1", image="images/p0001-code-1.png", caption="Listing 1", page=1),
    ]
    md = write_book(Book(title="T", blocks=blocks), tmp_path, []).read_text()
    assert "![E = mc^2](images/p0001-formula-1.png)" in md
    assert "![formula](images/p0001-formula-2.png)" in md
    assert 'src="images/p0001-code-1.png" alt="x = 1"/><figcaption>Listing 1' in md
    assert "```" not in md


def test_read_report_without_report_json_is_empty(tmp_path):
    assert read_report(tmp_path) == []


def test_report_round_trip(tmp_path):
    findings = [Finding(3, "ocr", "warning", "low confidence"), Finding(0, "info", "info", "ü")]
    write_book(Book(title="T"), tmp_path, findings)
    assert read_report(tmp_path) == findings


def failing_write(monkeypatch, error):
    """book.md cannot be written: the write raises `error`, as when a virus scanner removes it."""
    write_text = Path.write_text

    def fake(self, *args, **kwargs):
        if self.name == "book.md":
            raise error
        return write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake)


def blocked(winerror=None, errno=22):
    error = OSError(errno, "Invalid argument", "book.md")
    if winerror is not None:
        error.winerror = winerror  # set by hand: the attribute exists only on Windows
    return error


@pytest.mark.parametrize("error", [blocked(), blocked(winerror=225, errno=13)])
def test_book_md_that_antivirus_removed_gives_one_plain_error(tmp_path, monkeypatch, error):
    monkeypatch.setattr(sys, "platform", "win32")
    failing_write(monkeypatch, error)
    with pytest.raises(RemovedByAntivirus) as caught:
        write_book(Book(title="T"), tmp_path / "x.book", [])
    message = str(caught.value)
    assert str(tmp_path / "x.book" / "book.md") in message
    assert "antivirus" in message.lower() and "look like malware" in message
    assert "exclude eco's data folder" in message and "from scanning" in message
    assert not any(word in message.lower() for word in ("disable", "turn off", "switch off"))
    assert caught.value.__cause__ is error


@pytest.mark.parametrize(
    "platform, error",
    [("win32", blocked(errno=28)), ("linux", blocked()), ("darwin", blocked(winerror=225))],
)
def test_other_write_errors_pass_unchanged(tmp_path, monkeypatch, platform, error):
    monkeypatch.setattr(sys, "platform", platform)
    failing_write(monkeypatch, error)
    with pytest.raises(OSError) as caught:
        write_book(Book(title="T"), tmp_path / "x.book", [])
    assert caught.value is error


def failing_read(monkeypatch, error):
    """book.md is there but cannot be read: the read raises `error`, as when a virus scanner holds
    it after detecting a threat, before it moves the file away."""
    read_text = Path.read_text

    def fake(self, *args, **kwargs):
        if self.name == "book.md":
            raise error
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake)


@pytest.mark.parametrize("error", [blocked(), blocked(winerror=225, errno=13)])
def test_a_book_md_that_antivirus_holds_gives_one_plain_error_when_read(
    tmp_path, monkeypatch, error
):
    folder = tmp_path / "x.book"
    write_book(Book(title="T"), folder, [])
    monkeypatch.setattr(sys, "platform", "win32")
    failing_read(monkeypatch, error)
    with pytest.raises(RemovedByAntivirus) as caught:
        load_source(folder)
    message = str(caught.value)
    assert message.startswith(f"Could not read {folder / 'book.md'}. Antivirus software may")
    assert message.endswith("You can exclude the folder that holds this file from scanning.")
    assert "look like malware" in message and "data folder" not in message
    assert not any(word in message.lower() for word in ("disable", "turn off", "switch off"))
    assert caught.value.__cause__ is error


@pytest.mark.parametrize(
    "platform, error",
    [("win32", blocked(errno=13)), ("linux", blocked()), ("darwin", blocked(winerror=225))],
)
def test_other_read_errors_pass_unchanged(tmp_path, monkeypatch, platform, error):
    folder = tmp_path / "x.book"
    write_book(Book(title="T"), folder, [])
    monkeypatch.setattr(sys, "platform", platform)
    failing_read(monkeypatch, error)
    with pytest.raises(OSError) as caught:
        load_source(folder)
    assert caught.value is error


def test_a_book_md_missing_right_after_eco_wrote_it_gives_one_plain_error(tmp_path):
    folder = tmp_path / "x.book"
    write_book(Book(title="T"), folder, [])
    (folder / "book.md").unlink()  # what a virus scanner that moved it away leaves
    with pytest.raises(RemovedByAntivirus) as caught:
        load_source(folder, just_written=True)
    message = str(caught.value)
    assert message.startswith(f"Could not find {folder / 'book.md'}. Antivirus software may")
    assert message.endswith("You can exclude the folder that holds this file from scanning.")
    assert not any(word in message.lower() for word in ("disable", "turn off", "switch off"))
    assert isinstance(caught.value.__cause__, FileNotFoundError)


def test_a_book_folder_of_the_user_without_book_md_is_the_normal_error(tmp_path):
    folder = tmp_path / "mine.book"
    folder.mkdir()
    with pytest.raises(FileNotFoundError):
        load_source(folder)
