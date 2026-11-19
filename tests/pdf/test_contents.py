import unicodedata
from pathlib import Path

import pytest

from eco.book import Block
from eco.pdf import code, contents, pages, regions
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
    # read in columns: the order is inferred from the layout
    assert [(f.page, f.kind, f.level) for f in findings] == [(1, "contents_rebuilt", "warning")]


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


def test_numbered_chapter_zones_finish_both_columns_before_the_next_chapter(fixtures_dir):
    out = rebuilt(fixtures_dir["column_layouts"], 6, (62, 92, 548, 280))
    assert [text for _, text in out] == [
        "3",
        "Team Construct",
        "Roles performed within a team",
        "Team lead",
        "Ways to organize a team",
        "Summary",
        "4",
        "Communication Breakdown",
        "Internal team communication",
        "Communicating with stakeholders",
        "Scenario A",
        "Review questions",
    ]


@pytest.mark.parametrize(
    "page, box, lines",
    [
        # newspaper flow: chapter 4's entries go on at the top of the right column, level with
        # the "3", so the chapter numbers do not stand alone and the columns are read in turn
        (
            1,
            (62, 92, 548, 290),
            ["3", "Team Construct", "Roles performed within a team", "Team lead"]
            + ["Summary of roles", "4", "Communication Breakdown", "Internal team communication"]
            + ["Talking to stakeholders", "Scenario A", "Scenario B", "Review questions"],
        ),
        # a page number alone on its line is no taller than the text: no chapter number
        (
            2,
            (62, 92, 548, 210),
            ["Alpha steps", "Beta steps", "Gamma steps", "Detecting lateral movement with"]
            + ["remote services", "12", "Delta steps", "Zeta notes", "Eta notes", "Theta notes"],
        ),
        # in the back half (an index) chapter zones are read as plain columns
        (
            4,
            (62, 92, 548, 280),
            ["3", "Team Construct", "Roles performed within a team", "Team lead", "4"]
            + ["Communication Breakdown", "Internal team communication"]
            + ["Communicating with stakeholders", "Ways to organize a team", "Summary"]
            + ["Scenario A", "Review questions"],
        ),
    ],
)
def test_a_number_alone_starts_a_chapter_zone_only_when_it_is_clearly_a_chapter_number(
    fixtures_dir, page, box, lines
):
    out = rebuilt(fixtures_dir["chapter_layouts"], page, box)
    assert [text for _, text in out] == lines


def levels(pdf, page, box):
    _, findings = rebuild_contents(pdf, [Block("contents", page=page, bbox=box)], pages_of(pdf))
    return [(f.kind, f.level) for f in findings]


def test_contents_read_in_columns_or_across_a_wide_gap_are_a_warning(fixtures_dir):
    warning = [("contents_rebuilt", "warning")]
    # the chapter rule fired; columns; an index in columns
    assert levels(fixtures_dir["column_layouts"], 6, (62, 92, 548, 280)) == warning
    assert levels(fixtures_dir["chapter_layouts"], 1, (62, 92, 548, 290)) == warning
    assert levels(fixtures_dir["column_layouts"], 9, (62, 92, 475, 146)) == warning
    # one column, but a line holds a title a column's width after another: no gutter was found
    assert levels(fixtures_dir["chapter_layouts"], 3, (62, 92, 548, 146)) == warning
    _, findings = rebuild_contents(
        fixtures_dir["chapter_layouts"],
        [Block("contents", page=3, bbox=(62, 92, 548, 146))],
        pages_of(fixtures_dir["chapter_layouts"]),
    )
    assert findings[0].message.endswith("Order inferred from the layout; check this page.")


def test_a_plain_one_column_read_is_info(fixtures_dir):
    info = [("contents_rebuilt", "info")]
    assert levels(fixtures_dir["contents_layouts"], 1, (60.0, 90.0, 560.0, 260.0)) == info
    # labels beside their titles are no column
    assert levels(fixtures_dir["column_layouts"], 3, (62, 92, 548, 182)) == info


@pytest.mark.parametrize("module", [contents, pages, code, regions])
def test_the_modules_that_read_the_text_layer_hold_no_invisible_character(module):
    # a literal U+FFFE that an editor drops would make `.replace("", "-")` of the hyphen marker,
    # and one an editor keeps works but cannot be seen: the hyphen table uses escapes (R-90)
    source = Path(module.__file__).read_text(encoding="utf-8")
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
