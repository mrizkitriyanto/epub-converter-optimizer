from eco.book import Block
from eco.pdf.pages import PageInfo
from eco.pdf.reading_order import fix_reading_order

PAGES = {1: PageInfo(1, 612, 792, 0, 0, 500, 0), 2: PageInfo(2, 612, 792, 0, 0, 500, 0)}


def block(text, x0, y0, x1, y1, page=1):
    return Block("paragraph", text=text, page=page, bbox=(x0, y0, x1, y1))


def two_column_page(title_x=(54, 558), page=1):
    x0, x1 = title_x
    return {
        "T": block("T", x0, 60, x1, 80, page),
        "A": block("A", x0, 90, x1, 100, page),
        "Abstract": block("Abstract", 54, 120, 300, 130, page),
        "abs": block("abs", 54, 130, 300, 300, page),
        "1. Introduction": block("1. Introduction", 54, 310, 300, 320, page),
        "intro": block("intro", 54, 320, 300, 700, page),
        "pic": block("pic", 312, 120, 558, 240, page),
        "right1": block("right1", 312, 250, 558, 480, page),
        "right2": block("right2", 312, 490, 558, 700, page),
    }


BROKEN = ["T", "A", "pic", "right1", "right2", "Abstract", "abs", "1. Introduction", "intro"]
FIXED = ["T", "A", "Abstract", "abs", "1. Introduction", "intro", "pic", "right1", "right2"]


def test_two_column_page_is_reordered():
    page = two_column_page()
    blocks, findings = fix_reading_order([page[t] for t in BROKEN], PAGES)
    assert [b.text for b in blocks] == FIXED
    assert [(f.page, f.kind, f.level) for f in findings] == [(1, "reading_order_fixed", "info")]


def test_centred_narrow_title_does_not_hide_the_columns():
    page = two_column_page(title_x=(200, 412))
    blocks, findings = fix_reading_order([page[t] for t in BROKEN], PAGES)
    assert [b.text for b in blocks] == FIXED
    assert len(findings) == 1


def test_single_column_page_is_unchanged():
    original = [block(t, 54, 100 + 50 * i, 558, 140 + 50 * i) for i, t in enumerate("abcd")]
    blocks, findings = fix_reading_order(original, PAGES)
    assert blocks == original
    assert findings == []


def test_already_ordered_columns_give_no_finding():
    page = two_column_page()
    blocks, findings = fix_reading_order([page[t] for t in FIXED], PAGES)
    assert [b.text for b in blocks] == FIXED
    assert findings == []


def test_pages_are_not_mixed_and_blocks_without_bbox_keep_position():
    p1, p2 = two_column_page(), two_column_page(page=2)
    note = Block("paragraph", text="note", page=1)
    original = [note] + [p1[t] for t in BROKEN] + [p2[t] for t in FIXED]
    snapshot = list(original)
    blocks, findings = fix_reading_order(original, PAGES)
    assert original == snapshot
    assert [b.text for b in blocks] == ["note", *FIXED, *FIXED]
    assert [b.page for b in blocks] == [1] * 10 + [2] * 9
    assert [f.page for f in findings] == [1]


def test_page_missing_from_pages_is_unchanged():
    page = two_column_page(page=3)
    original = [page[t] for t in BROKEN]
    blocks, findings = fix_reading_order(original, PAGES)
    assert blocks == original
    assert findings == []
