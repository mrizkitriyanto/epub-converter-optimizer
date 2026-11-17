"""Fast checks of the acceptance helpers, so a mistake in them shows on every run and not only
after an hour on the owner's samples."""

from metrics import (
    code_blocks,
    epub_text,
    headings,
    pages,
    sequence_scores,
    word_recall,
    words,
    x4_problems,
)

from eco.epub.optimizer import optimize_epub
from eco.options import Options


def seq(text):
    return text.split()


LETTERS = seq("a b c d e f g h")


def test_words_keep_the_text_and_drop_the_markup():
    text = (
        "<!-- page: 3 -->\n![formula](images/p0003-formula-1.png)\n"
        "Don't miss [the Café](http://x.org/a_b) &amp; <b>Ünï</b> 42."
    )
    assert words(text) == ["don't", "miss", "the", "café", "ünï", "42"]
    assert words(r"see \[1\](x) there") == ["see", "1", "x", "there"]  # how eco writes `[1](x)`


def test_identical_text_scores_one():
    assert sequence_scores(LETTERS, LETTERS) == (1.0, 1.0)


def test_extra_output_words_cost_precision_only():
    assert sequence_scores(LETTERS, seq("a b c x y d e f g h")) == (0.8, 1.0)


def test_a_missing_word_inside_the_span_costs_recall_only():
    assert sequence_scores(LETTERS, seq("a b c d f g h")) == (1.0, 0.875)


def test_truth_outside_the_matched_span_is_not_missed():
    assert sequence_scores(seq("x y z a b c d e f"), seq("a b c d e f")) == (1.0, 1.0)


def test_blocks_of_fewer_than_three_words_do_not_count():
    # only "c d e" is kept: 3 of 6 output words, all of the 3-word span it covers in the truth
    assert sequence_scores(seq("a b x c d e"), seq("a b y c d e")) == (0.5, 1.0)


def test_nothing_in_common_scores_zero():
    assert sequence_scores(seq("a b c"), seq("x y z")) == (0.0, 0.0)
    assert sequence_scores(seq("a b c"), []) == (0.0, 0.0)


def test_word_recall_is_the_share_of_the_page_found_in_order():
    assert word_recall(LETTERS, seq("a b c d f g h")) == 0.875
    assert word_recall(LETTERS, []) == 0.0


BOOK = """\
---
title: "T"
---

<!-- page: 1 -->

# Title

Some text.

<!-- page: 2 -->

## 1\\. Intro

```
# not a heading
$ ls    -l
```

<!-- page: 3 -->

![formula](images/p0003-formula-1.png)
"""


def test_readers_of_a_book_md():
    assert pages(BOOK, 2, 3).startswith("## 1")
    assert "Title" not in pages(BOOK, 2, 3) and "formula" not in pages(BOOK, 1, 2)
    assert headings(BOOK) == ["Title", "1. Intro"]
    assert code_blocks(BOOK) == [["# not a heading", "$ ls -l"]]


def test_epub_text_is_the_spine_bodies_in_order(messy_epub):
    text = epub_text(messy_epub)
    assert text.index("Chapter One") < text.index("Chapter&nbsp;Two")
    assert "<title>" not in text and "float:right" not in text


def test_x4_problems_finds_what_the_optimizer_removes(messy_epub, tmp_path):
    problems = "\n".join(x4_problems(messy_epub))
    for found in ("photo.jpg: progressive", "photo.jpg: 1650x835", ".gif", ".webp", ".svg", ".otf"):
        assert found in problems
    optimized = tmp_path / "x4.epub"
    optimize_epub(messy_epub, optimized, Options(device="x4"))
    assert x4_problems(optimized) == []
