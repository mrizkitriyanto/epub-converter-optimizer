import unicodedata
from pathlib import Path

import pytest

from eco.book import Block
from eco.pdf import contents
from eco.pdf.contents import _entry, _Run, rebuild_contents
from eco.pdf.pages import PageInfo, inspect_pdf

TABLE = "<table><tr><td>x</td></tr></table>"


def line(*runs):
    """A line of 11 pt runs: (left, right, text) each; digits are 7 pt high, the rest 10 pt."""
    return [
        _Run(100.0, 107.0 if text.isdigit() else 110.0, left, right, text)
        for left, right, text in runs
    ]


@pytest.mark.parametrize(
    "runs, entry",
    [
        # no page number: every word stays
        (line((72, 140, "Editing with vi")), "Editing with vi"),
        (line((72, 110, "Lab mix")), "Lab mix"),
        (line((72, 180, "Hunting on Windows 10")), "Hunting on Windows 10"),
        (line((72, 130, "What next...")), "What next..."),
        (line((72, 165, "Hunting on Windows"), (167, 177, "10")), "Hunting on Windows 10"),
        (line((72, 160, "Index .......... ic")), "Index .......... ic"),  # no roman numeral
        (line((72, 110, "Rock"), (112, 120, "&"), (530, 540, "45")), "Rock &"),  # not a leader
        # a page number: it goes, and its leader with it
        (line((72, 160, "Preface .......... xi")), "Preface"),
        (line((72, 180, "Hunting on Windows 10"), (530, 540, "45")), "Hunting on Windows 10"),
        (line((72, 200, "Chapter 3 Basics ........ 117")), "Chapter 3 Basics"),
        (line((72, 110, "Preface"), (112, 300, ". . . . . . . ."), (530, 540, "xi")), "Preface"),
        (line((72, 110, "Preface"), (112, 540, ". . . . . . . . 45")), "Preface"),
        (line((72, 300, "Preface . . . . . . . ."), (302, 312, "45")), "Preface"),
        # a line that is only a number stays
        (line((72, 80, "1")), "1"),
    ],
)
def test_a_contents_line_loses_only_a_number_that_is_clearly_its_page_number(runs, entry):
    assert _entry(runs) == entry


def pages_of(pdf):
    return {info.number: info for info in inspect_pdf(pdf)}


def test_contents_are_rebuilt_in_reading_order_without_print_page_numbers(fixtures_dir):
    pdf = fixtures_dir["contents"]
    block = Block("contents", page=1, bbox=(60.0, 95.0, 560.0, 240.0), html=TABLE)
    out, findings = rebuild_contents(
        pdf, [Block("heading", "Contents", page=1), block], pages_of(pdf)
    )
    # A number after a leader goes. A number in the same run after one space is not clearly a
    # page number ("Hunting on Windows 10"), so it stays: a title word lost would be a failure.
    assert [(b.kind, b.text) for b in out] == [
        ("heading", "Contents"),
        ("paragraph", "Part One: Getting Ready for the Long Walk"),
        ("paragraph", "Alpha steps"),
        ("paragraph", "Beta steps"),
        ("paragraph", "Preface"),
        ("paragraph", "Delta notes 20"),
        ("paragraph", "Epsilon notes 21"),
        ("paragraph", "Zeta notes 22"),
        ("paragraph", "Part Two: Coming Home Again Much Later"),
        ("paragraph", "Eta work 31"),
        ("paragraph", "Iota work 35"),
    ]
    assert all(b.page == 1 for b in out)
    assert [(f.page, f.kind, f.level) for f in findings] == [(1, "contents_rebuilt", "info")]


def rebuilt(pdf, page, bbox, caption=""):
    block = Block("contents", page=page, bbox=bbox, html=TABLE, caption=caption)
    out, findings = rebuild_contents(pdf, [block], pages_of(pdf))
    assert [f.kind for f in findings] == ["contents_rebuilt"]
    return [(b.kind, b.text) for b in out]


def test_one_column_contents_with_page_numbers_as_runs_of_their_own(fixtures_dir):
    out = rebuilt(fixtures_dir["contents_layouts"], 1, (60.0, 90.0, 560.0, 260.0))
    assert out == [
        ("paragraph", "Part One: Basics of the work"),
        ("paragraph", "Preface"),
        ("paragraph", "Hunting on Windows 10"),
        ("paragraph", "Lab mix"),
        ("paragraph", "Editing with vi"),
        ("paragraph", "and other tools"),
        ("paragraph", "What next..."),
        ("paragraph", "Chapter Two Is A Long Title That Runs Across"),
        ("paragraph", "Chapter 3 Basics"),
    ]


def test_two_columns_with_page_numbers_as_runs_and_a_short_title_over_the_gutter(fixtures_dir):
    # Docling's box is not centred on the gutter: "Part Two" lies left of the box's middle
    out = rebuilt(fixtures_dir["contents_layouts"], 2, (60.0, 90.0, 600.0, 250.0))
    assert [text for _, text in out] == [
        "Part One: Getting Ready for the Long Walk",
        "Alpha steps",
        "Beta steps",
        "Gamma steps",
        "Delta notes",
        "Epsilon notes",
        "Zeta notes",
        "Part Two",
        "Eta work",
        "Theta work",
        "Iota work",
        "Kappa work",
    ]


def test_an_index_line_keeps_a_comma_whose_glyph_sits_low(fixtures_dir):
    out = rebuilt(fixtures_dir["contents_layouts"], 4, (60.0, 90.0, 560.0, 140.0))
    assert out == [
        ("list_item", "protecting 116, 117"),
        ("list_item", "pyramid 3"),
        ("list_item", "of pain 5"),
    ]


def test_the_caption_of_a_contents_block_comes_first(fixtures_dir):
    out = rebuilt(fixtures_dir["contents_layouts"], 1, (60.0, 90.0, 560.0, 140.0), "In brief")
    assert out == [
        ("paragraph", "In brief"),
        ("paragraph", "Part One: Basics of the work"),
        ("paragraph", "Preface"),
    ]


STEPS = ["Alpha steps", "Beta steps", "Gamma steps", "Delta steps"]
CHAPTERS = [
    "Chapter 1 Introduction",
    "Chapter 2 Methods",
    "Chapter 3 Results",
    "Chapter 4 Discussion",
    "Chapter 5 Summary",
]


@pytest.mark.parametrize(
    "page, box, lines",
    [
        # a short last column of contents, and a right column of one line
        (1, (62, 92, 548, 182), [*STEPS, "Epsilon steps", "Zeta notes", "Eta notes"]),
        (2, (62, 92, 548, 166), [*STEPS, "Zeta notes"]),
        # labels beside short titles are one column, with page numbers and without
        (3, (62, 92, 548, 182), CHAPTERS),
        (4, (62, 92, 205, 182), CHAPTERS),
        # a font change after other text stays in its line and its column, on either side
        (
            5,
            (62, 92, 425, 182),
            [
                "Alpha steps",
                "Beta steps",
                "Detecting lateral movement with PsExec",
                "Gamma steps",
                "Delta steps",
                "Eps notes",
                "Zeta notes",
                "Logs from auditd",
                "Theta notes",
                "Iota notes",
            ],
        ),
        # the last page of an index: six long entries on the left, three short ones on the right
        (
            7,
            (62, 92, 402, 182),
            [
                "web shells, detecting 101, 140",
                "Windows Event Forwarding 88",
                "Windows Management Instrumentation 63, 70",
                "workstation hunting 77",
                "WMI persistence 71, 72",
                "XDR platforms 30",
                "YARA rules 150",
                "zero trust 12",
                "Zeek 98",
            ],
        ),
        (
            8,
            (62, 92, 377, 146),
            ["apple 12", "banana 7, 9, see also fruit", "fruit 2", "kiwi 3", "lemon 4", "mango 8"],
        ),
        (
            9,
            (62, 92, 475, 146),
            ["acorn 1", "birch 2", "cedar 3", "dogwood 1", "elm 2", "fir 3"]
            + ["ginkgo 1", "hazel 2", "ivy 3"],
        ),
        (10, (62, 92, 385, 146), ["oak 2", "pine 3", "yew 4", "zelkova 40"]),
    ],
)
def test_one_column_or_two_in_a_box_that_hugs_the_text(fixtures_dir, page, box, lines):
    out = rebuilt(fixtures_dir["column_layouts"], page, box)
    assert [text for _, text in out] == lines


def test_a_hyphen_at_a_line_end_stays_a_hyphen(fixtures_dir):
    # PDFium gives it as "\x02" in a bounded text and as U+FFFE in a range of the page
    out = rebuilt(fixtures_dir["column_layouts"], 11, (62, 92, 200, 146))
    assert [text for _, text in out] == ["anomaly detec-", "tion 40", "audit logs 9"]


def test_contents_py_holds_no_invisible_character():
    # a literal U+FFFE that an editor drops would make `.replace("", "-")` of the hyphen marker
    source = Path(contents.__file__).read_text(encoding="utf-8")
    hidden = {c for c in source if unicodedata.category(c) in ("Cc", "Cf", "Cn", "Co", "Cs")}
    assert hidden <= {"\n"}


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
