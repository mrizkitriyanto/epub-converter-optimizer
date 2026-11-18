import pytest

from eco.book import Block
from eco.pdf.pages import Bookmark
from eco.pdf.structure import assign_heading_levels


def heading(text, page=1):
    return Block("heading", text, level=0, page=page)


def levels(blocks):
    return [b.level for b in blocks if b.kind == "heading"]


def test_without_bookmarks_all_caps_is_level_1_and_the_rest_level_2():
    blocks = [heading("SAPAAN RAMAH DI PAGI HARI"), heading("Sebuah Salam yang Hangat")]
    out, findings = assign_heading_levels(blocks, [])
    assert levels(out) == [1, 2]
    assert findings == []


@pytest.mark.parametrize("text", ["Chapter 3", "Bab 2 Pendahuluan", "BAB I"])
def test_without_bookmarks_chapter_words_are_level_1(text):
    assert levels(assign_heading_levels([heading(text)], [])[0]) == [1]


@pytest.mark.parametrize("text", ["ABC", "Chapters", "Bab", "Babak 1", "A1 B2 C3"])
def test_without_bookmarks_other_headings_are_level_2(text):
    assert levels(assign_heading_levels([heading(text)], [])[0]) == [2]


def test_bookmark_sets_level_of_matching_heading():
    blocks = [heading("Communication Breakdown", page=5)]
    out, findings = assign_heading_levels(blocks, [Bookmark("Communication Breakdown", 0, 5)])
    assert levels(out) == [1]
    assert findings == []


def test_match_is_case_insensitive_and_fuzzy():
    blocks = [heading("COMMUNICATION BREAKDOWNS", page=5)]
    out, _ = assign_heading_levels(blocks, [Bookmark("Communication Breakdown", 1, 5)])
    assert levels(out) == [2]


@pytest.mark.parametrize("page, matched", [(4, True), (6, True), (3, False), (7, False)])
def test_match_reaches_one_page_either_side_but_not_two(page, matched):
    blocks = [heading("Alpha", page), heading("Other", 5)]
    out, findings = assign_heading_levels(blocks, [Bookmark("Alpha", 0, 5)])
    assert sorted(b.level for b in out if b.text == "Alpha") == ([1] if matched else [1, 2])
    assert (findings == []) is matched


@pytest.mark.parametrize(
    "mark, text",
    [
        ("Chapter 3: Quiet Harbors", "3 Quiet Harbors"),
        ("Bab 2 Kebun Pagi", "2 Kebun Pagi"),
        ("3 Quiet Harbors", "CHAPTER 3. QUIET HARBORS"),
    ],
)
def test_a_chapter_label_in_one_title_and_a_bare_number_in_the_other_still_match(mark, text):
    out, findings = assign_heading_levels([heading(text, page=5)], [Bookmark(mark, 0, 5)])
    assert [(b.text, b.level) for b in out] == [(text, 1)]
    assert findings == []


def test_chapter_numbers_that_differ_do_not_match():
    blocks = [heading("12", page=5)]
    out, findings = assign_heading_levels(blocks, [Bookmark("Chapter 3", 0, 5)])
    assert [(b.text, b.level) for b in out] == [("Chapter 3", 1), ("12", 2)]
    assert [f.kind for f in findings] == ["heading_added"]


def test_dissimilar_heading_does_not_match():
    blocks = [heading("Something else entirely", page=5), Block("paragraph", "x", page=7)]
    out, findings = assign_heading_levels(blocks, [Bookmark("Communication Breakdown", 0, 5)])
    assert [b.text for b in out] == ["Communication Breakdown", "Something else entirely", "x"]
    assert levels(out) == [1, 2]
    assert [f.kind for f in findings] == ["heading_added"]


def test_unmatched_bookmark_inserts_heading_before_first_block_of_its_page():
    blocks = [
        Block("paragraph", "p5", page=5),
        Block("paragraph", "p7a", page=7),
        Block("paragraph", "p7b", page=7),
    ]
    out, findings = assign_heading_levels(blocks, [Bookmark(" Lost Chapter ", 1, 7)])
    assert [b.text for b in out] == ["p5", "Lost Chapter", "p7a", "p7b"]
    added = out[1]
    assert (added.kind, added.level, added.page) == ("heading", 2, 7)
    assert len(findings) == 1
    assert (findings[0].page, findings[0].kind, findings[0].level) == (7, "heading_added", "info")
    assert findings[0].message


def test_inserted_headings_on_one_page_keep_bookmark_order():
    blocks = [Block("paragraph", "p", page=3)]
    marks = [Bookmark("First", 0, 3), Bookmark("Second", 1, 3)]
    out, _ = assign_heading_levels(blocks, marks)
    assert [b.text for b in out] == ["First", "Second", "p"]


def test_bookmark_on_a_page_without_blocks_goes_before_the_next_page():
    blocks = [Block("paragraph", "p1", page=1), Block("paragraph", "p4", page=4)]
    out, _ = assign_heading_levels(blocks, [Bookmark("Gap", 0, 3)])
    assert [b.text for b in out] == ["p1", "Gap", "p4"]


def test_bookmark_outside_the_page_range_is_skipped_silently():
    blocks = [Block("paragraph", "p", page=5), Block("paragraph", "q", page=6)]
    marks = [Bookmark("Before", 0, 4), Bookmark("After", 0, 7)]
    out, findings = assign_heading_levels(blocks, marks)
    assert [b.text for b in out] == ["p", "q"]
    assert findings == []


def test_bookmarks_are_matched_in_order_so_the_first_takes_a_shared_heading():
    blocks = [heading("Introduction to Testing", page=2)]
    marks = [
        Bookmark("Introduction to Testing Methods", 1, 2),
        Bookmark("Introduction to Testing", 0, 2),
    ]
    out, findings = assign_heading_levels(blocks, marks)
    assert [(b.text, b.level) for b in out] == [
        ("Introduction to Testing", 1),
        ("Introduction to Testing", 2),
    ]
    assert [f.kind for f in findings] == ["heading_added"]


def test_one_heading_matches_one_bookmark_only():
    blocks = [heading("Same Title", page=2)]
    marks = [Bookmark("Same Title", 0, 2), Bookmark("Same Title", 1, 2)]
    out, findings = assign_heading_levels(blocks, marks)
    assert [(b.text, b.level) for b in out] == [("Same Title", 2), ("Same Title", 1)]
    assert [f.kind for f in findings] == ["heading_added"]


def test_best_scoring_heading_wins_among_candidates():
    blocks = [heading("Chapter Ten", page=2), heading("Chapter One", page=2)]
    out, findings = assign_heading_levels(blocks, [Bookmark("Chapter One", 0, 2)])
    assert levels(out) == [2, 1]
    assert findings == []


def test_level_is_capped_at_6():
    blocks = [heading("Deep", page=1)]
    out, _ = assign_heading_levels(blocks, [Bookmark("Deep", 9, 1)])
    assert levels(out) == [6]


def test_unmatched_heading_gets_deepest_plus_2_capped():
    marks = [Bookmark("Part", 0, 1), Bookmark("Section", 2, 1)]
    blocks = [heading("Part", 1), heading("Section", 1), heading("Stray", 1)]
    assert levels(assign_heading_levels(blocks, marks)[0]) == [1, 3, 4]
    deep = [Bookmark("Part", 5, 1)]
    out, _ = assign_heading_levels([heading("Part", 1), heading("Stray", 1)], deep)
    assert levels(out) == [6, 6]


def test_non_heading_blocks_pass_through_and_input_is_not_mutated():
    para = Block("paragraph", "SAPAAN RAMAH", level=0, page=1)
    head = heading("Alpha", page=1)
    blocks = [para, head]
    out, _ = assign_heading_levels(blocks, [Bookmark("Alpha", 0, 1)])
    assert out[0] is para
    assert head.level == 0
    assert out[1].level == 1
    assert blocks == [para, head]
