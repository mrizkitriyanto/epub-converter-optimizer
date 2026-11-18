from eco.book import Block
from eco.pdf.contents import rebuild_contents
from eco.pdf.pages import PageInfo, inspect_pdf

TABLE = "<table><tr><td>x</td></tr></table>"


def pages_of(pdf):
    return {info.number: info for info in inspect_pdf(pdf)}


def test_contents_are_rebuilt_in_reading_order_without_print_page_numbers(fixtures_dir):
    pdf = fixtures_dir["contents"]
    block = Block("contents", page=1, bbox=(60.0, 95.0, 560.0, 240.0), html=TABLE)
    out, findings = rebuild_contents(
        pdf, [Block("heading", "Contents", page=1), block], pages_of(pdf)
    )
    assert [(b.kind, b.text) for b in out] == [
        ("heading", "Contents"),
        ("paragraph", "Part One: Getting Ready for the Long Walk"),
        ("paragraph", "Alpha steps"),
        ("paragraph", "Beta steps"),
        ("paragraph", "Preface"),
        ("paragraph", "Delta notes"),
        ("paragraph", "Epsilon notes"),
        ("paragraph", "Zeta notes"),
        ("paragraph", "Part Two: Coming Home Again Much Later"),
        ("paragraph", "Eta work"),
        ("paragraph", "Iota work"),
    ]
    assert all(b.page == 1 for b in out)
    assert [(f.page, f.kind, f.level) for f in findings] == [(1, "contents_rebuilt", "info")]


def test_an_index_keeps_its_numbers(fixtures_dir):
    pdf = fixtures_dir["contents"]
    block = Block("contents", page=3, bbox=(60.0, 95.0, 560.0, 140.0), html=TABLE)
    out, findings = rebuild_contents(pdf, [block], pages_of(pdf))
    assert [(b.kind, b.text) for b in out] == [
        ("list_item", "apple 12, 14"),
        ("list_item", "pie 15"),
        ("list_item", "banana 7"),
        ("list_item", "cherry 3, 9"),
    ]
    assert [f.kind for f in findings] == ["contents_rebuilt"]


def test_a_scanned_page_keeps_doclings_table(fixtures_dir):
    scan = PageInfo(1, 612.0, 792.0, 0.0, 0.0, 0, 1.0)
    block = Block("contents", page=1, bbox=(60.0, 95.0, 560.0, 240.0), html=TABLE)
    out, findings = rebuild_contents(fixtures_dir["contents"], [block], {1: scan})
    assert out == [Block("table", page=1, bbox=block.bbox, html=TABLE)]
    assert findings == []


def test_a_box_without_text_keeps_doclings_table(fixtures_dir):
    pdf = fixtures_dir["contents"]
    block = Block("contents", page=1, bbox=(60.0, 600.0, 560.0, 700.0), html=TABLE)
    out, _ = rebuild_contents(pdf, [block], pages_of(pdf))
    assert [b.kind for b in out] == ["table"]
