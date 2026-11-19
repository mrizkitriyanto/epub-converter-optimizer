"""Contents and index pages, rebuilt from the PDF text layer in reading order (agent decision Q-23).

Docling reads a page of contents as a table (`document_index`), and its table model forces a
two-column page into a grid whose rows pair entries of both columns. On a page with a text layer
the entries are read again from that layer, one entry per line. The text runs are grouped into
lines by their height on the page; a page is read in columns only where its text has a gutter
(`_gutter`), and then a full-width line ends the columns above it, which are read left column
first; on a contents page a chapter number set apart does too (agent decision Q-28). Otherwise
the lines are read top to bottom, each left to right. Where the order is inferred from the
layout, the finding is a warning."""

import re
import statistics
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import NamedTuple

from eco.book import Block
from eco.events import Finding
from eco.pdf.pages import Bbox, PageInfo, _open, to_pdfium_rect

_PAD = 2.0
# pt: a run that starts this close left of a column's edge starts at it. A larger letter heading
# ("T" of an index) starts 1.3 pt left of the entries below it; a gutter is a line high (8-11 pt).
_EDGE = 2.0
_ALIGN = 1.0  # pt: lines whose text starts this close together start a column
# The left one of two columns spans at least this share of the page width: half the text area
# less the gutter is 0.35 or more on Threat Hunting and the fixtures, and the first of three
# columns about 0.3. A column of labels beside their titles ("Chapter 1") spans 0.1 to 0.15.
_COLUMN = 0.2
_CHAPTER = 1.25  # a chapter number is at least this many times as high as the median text
_ROMAN = re.compile(r"m{0,3}(c[md]|d?c{0,3})(x[cl]|l?x{0,3})(i[xv]|v?i{0,3})")
_LEADER = r"(?:[.\u00b7\u2026]\s*){4,}"  # a dot leader: four dots or more; "What next..." has three
_NUMBER_RUN = re.compile(rf"({_LEADER})?(\d+|[ivxlcdm]+)")
_NUMBER_AFTER_LEADER = re.compile(rf"(.*?\w.*?)\s*{_LEADER}(\d+|[ivxlcdm]+)")
_ENDS_IN_LEADER = re.compile(rf"\s*{_LEADER}$")
_LEADER_RUN = re.compile(_LEADER)
_CLOSING = ",;:)]"  # punctuation that belongs to the word before it
_HYPHEN_MARKS = str.maketrans({"\ufffe": "-", "\x02": "-"})


class _Run(NamedTuple):
    """A text run of the page: its box, with `top` and `bottom` growing downwards, and its text."""

    top: float
    bottom: float
    left: float
    right: float
    text: str

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def middle(self) -> float:
        return (self.top + self.bottom) / 2


def _runs(pdf: Path, info: PageInfo, bbox: Bbox) -> list[_Run]:
    """The text runs whose centre lies inside `bbox`."""
    left, bottom, right, top = to_pdfium_rect(info, bbox)
    runs = []
    with _open(pdf) as document:
        textpage = document[info.number - 1].get_textpage()
        for index in range(textpage.count_rects()):
            x0, y0, x1, y1 = textpage.get_rect(index)
            inside = left - _PAD <= (x0 + x1) / 2 <= right + _PAD
            if not inside or not bottom - _PAD <= (y0 + y1) / 2 <= top + _PAD:
                continue
            # PDFium marks a hyphen at a line end: U+FFFE in a range of the text, "\x02" in a
            # bounded text. Keep it as a hyphen.
            text = textpage.get_text_bounded(x0, y0, x1, y1).translate(_HYPHEN_MARKS)
            if text.strip():
                runs.append(_Run(-y1, -y0, x0, x1, " ".join(text.split())))
    return runs


def _page_number(text: str) -> bool:
    """True for a number that can be a print page number: arabic, or a valid lowercase roman."""
    return text.isdigit() or bool(_ROMAN.fullmatch(text))


def _is_text(run: _Run) -> bool:
    """A run that can start an entry: it has a letter, and it is not a page number."""
    found = _NUMBER_RUN.fullmatch(run.text)
    return bool(re.search(r"[^\W\d_]", run.text)) and not (found and _page_number(found[2]))


def _rows(runs: list[_Run]) -> list[list[_Run]]:
    """`runs` as lines from top to bottom, each read left to right. A run joins a line when its
    middle lies within the height of the line's tallest run, or when half the lower of the two
    heights overlaps: a comma or a dot leader whose glyph box sits low stays in its line. One run's
    box, not the line's, is the measure, so the lines of two columns do not run into each other."""
    rows: list[list[_Run]] = []
    for run in sorted(runs, key=lambda r: r.middle):
        tall = max(rows[-1], key=lambda r: r.height) if rows else None
        overlap = min(tall.bottom, run.bottom) - max(tall.top, run.top) if tall else 0.0
        if tall and (
            tall.top <= run.middle <= tall.bottom or overlap >= min(tall.height, run.height) / 2
        ):
            rows[-1].append(run)
        else:
            rows.append([run])
    return [sorted(row, key=lambda r: r.left) for row in rows]


def _full_width(row: list[_Run], x: float, gap: float, start: float) -> bool:
    """True for a line across the columns: a text run of it spans the right column's edge `x`; or
    nothing of it lies right of `x`, and its text reaches into the gutter before `x` (`gap` wide)
    or its first text run starts in the right half of the left column, as a short title centred
    over the gutter does. Where a later run starts says nothing: an italic word after other text
    of its line stays in the line's column."""
    texts = [r for r in row if _is_text(r)]
    if any(r.left < x - _EDGE and r.right > x + _EDGE for r in texts):
        return True
    if not texts or any(r.left >= x - _EDGE for r in texts):
        return False
    return any(r.right > x - gap for r in texts) or texts[0].left > (start + x) / 2


def _numbered(part: list[_Run]) -> bool:
    """True when a part of a line ends in a page number that is a run of its own."""
    found = _NUMBER_RUN.fullmatch(part[-1].text) if len(part) > 1 else None
    return bool(found and _page_number(found[2]))


def _chapter_starts(rows: list[list[_Run]], x: float, gap: float) -> set[int]:
    """The indexes of the lines that start a numbered chapter zone (agent decision Q-28): a number
    alone in its line left of the right column's edge `x`, and clearly a chapter number, at least
    `_CHAPTER` times as high as the median text `gap` (Threat Hunting's chapter numbers are 1.3 to
    1.7 times as high as its text). None when a line whose left part is only numbers has a run of
    the right column level with it: the numbers are not set apart then, as on a page where a
    chapter's entries flow on at the top of the next column."""
    right = [run for row in rows for run in row if run.left >= x - _EDGE]
    alone = []
    for index, row in enumerate(rows):
        left = [r for r in row if r.left < x - _EDGE]
        if not left or not all(r.text.isdigit() for r in left):
            continue
        top, bottom = min(r.top for r in left), max(r.bottom for r in left)
        if any(min(r.bottom, bottom) > max(r.top, top) for r in right):
            return set()
        alone.append(index)
    return {i for i in alone if len(rows[i]) == 1 and rows[i][0].height >= _CHAPTER * gap}


def _gutter(runs: list[_Run], width: float) -> tuple[float, float, float] | None:
    """Where the right column starts, how wide the gutter before it is at least, and where the
    left column starts, when the runs stand in columns; None when they do not.

    The gutter is a band one line high (the median height of the text) before the right column's
    edge `x`. An edge is where a text run begins its line, or follows the run before it by the
    gutter's width: an italic or code word after other text, a word space away, is no edge, and
    page numbers and dot leaders make none. An edge makes two columns when:
    - the left column spans a fifth of the page width or more; a column of labels ("Chapter 1")
      beside their titles spans less;
    - two lines or more start at it, or one line level with the first line of its section (the
      block, or the part below a full-width line): a last column of one line. A word far right
      in a later line is no column;
    - two lines or more lie left of it, and fewer lines cross it than that. A line crosses when
      it is full-width (`_full_width`) or a run of it, a page number too, reaches into the gutter;
    - not only the right part of the lines ends in page numbers that are runs of their own: then
      the left part holds labels of the titles, not entries of their own.
    Of several edges, the one fewest lines cross wins, then the one most lines start at, then the
    leftmost."""
    texts = [r for r in runs if _is_text(r)]
    if len(texts) < 3:
        return None
    gap = statistics.median(r.height for r in texts)
    start = min(r.left for r in texts)
    rows = _rows(runs)
    edges = {
        run.left
        for row in rows
        for before, run in zip([None, *row], row, strict=False)
        if _is_text(run) and (before is None or run.left - before.right >= gap)
    }
    best: tuple[int, int, float] | None = None
    for x in sorted(edges):
        if x - start < _COLUMN * width:
            continue
        crossed, parts, level, top = 0, [], [], None
        for row in rows:
            if _full_width(row, x, gap, start):
                crossed, top = crossed + 1, None  # a new section begins below it
                continue
            top = min(r.top for r in row) if top is None else top
            left = [r for r in row if r.left < x - _EDGE]
            right = [r for r in row if r.left >= x - _EDGE]
            if any(r.right > x - gap for r in left):
                crossed += 1
            else:
                parts.append((left, right))
            texts = [r for r in right if _is_text(r)]
            if texts and texts[0].left <= x + _ALIGN:  # a line that starts at the edge
                level.append(texts[0].top - top <= gap)
        lefts = sum(any(map(_is_text, left)) for left, _ in parts)
        if (len(level) < 2 and not any(level)) or lefts < 2 or crossed >= lefts:
            continue
        if any(_numbered(right) for _, right in parts) and not any(
            _numbered(left) for left, _ in parts
        ):
            continue
        if best is None or (crossed, -len(level), x) < best:
            best = (crossed, -len(level), x)
    return None if best is None else (best[2], gap, start)


def _reading_order(
    runs: list[_Run], width: float, *, chapter_starts: bool = False
) -> list[list[_Run]]:
    """The lines of `runs` in reading order, on a page `width` wide. In columns a full-width line
    ends the columns above it, which are read left column first; with `chapter_starts` so does a
    chapter number set apart (`_chapter_starts`). Each column is read the same way, so a third
    column is found inside the second."""
    found = _gutter(runs, width)
    if found is None:
        return _rows(runs)
    x, gap, start = found
    lines: list[list[_Run]] = []
    left: list[_Run] = []
    right: list[_Run] = []
    rows = _rows(runs)
    starts = _chapter_starts(rows, x, gap) if chapter_starts else set()
    for index, row in enumerate(rows):
        if _full_width(row, x, gap, start) or index in starts:
            lines += _reading_order(left, width) + _reading_order(right, width) + [row]
            left, right = [], []
        else:
            for run in row:
                (left if run.left < x - _EDGE else right).append(run)
    return lines + _reading_order(left, width) + _reading_order(right, width)


def _inferred(runs: list[_Run], width: float) -> bool:
    """True when the reading order of `runs` is inferred from their layout, so it can be wrong: the
    page is read in columns (`_gutter`), or read as one column although a line of it holds text
    that follows other text a gutter's width away and a column's width from the left edge, two
    columns that `_gutter` did not accept. A plain one-column read gives False."""
    if _gutter(runs, width) is not None:
        return True
    texts = [r for r in runs if _is_text(r)]
    if not texts:
        return False
    gap = statistics.median(r.height for r in texts)
    start = min(r.left for r in texts)
    rows = _rows(runs)
    return any(
        _is_text(run) and run.left - before.right >= gap and run.left - start >= _COLUMN * width
        for row in rows
        for before, run in pairwise(row)
    )


def _text(row: list[_Run]) -> str:
    """The text of a line: its runs joined by a space, but for a comma or the like that touches
    the run before it."""
    text = row[0].text
    for before, run in pairwise(row):
        touches = run.left - before.right < max(before.height, run.height) / 4
        text += ("" if touches and run.text[0] in _CLOSING else " ") + run.text
    return text


def _without_page_number(text: str) -> str:
    """The text of a contents line without a print page number that follows a dot leader."""
    found = _NUMBER_AFTER_LEADER.fullmatch(text)
    return found[1] if found and _page_number(found[2]) else text


def _entry(row: list[_Run]) -> str:
    """A line of contents without its print page number and dot leader. A number goes only when it
    is clearly a page number: a run of its own after a gap of half its height or after a leader,
    or a number that ends a run after a leader. Otherwise the line keeps all of its text: a title
    word lost is a failure (spec section 5), a page number kept is not."""
    *head, last = row
    found = _NUMBER_RUN.fullmatch(last.text)
    if head and found and _page_number(found[2]):
        apart = last.left - head[-1].right >= last.height / 2
        led = bool(found[1] or _ENDS_IN_LEADER.search(head[-1].text))
        while head and _LEADER_RUN.fullmatch(head[-1].text):  # a leader that is a run of its own
            head, led = head[:-1], True
        if head and (apart or led):
            return _ENDS_IN_LEADER.sub("", _text(head))
    return _without_page_number(_text(row))


def rebuild_contents(
    pdf: Path, blocks: list[Block], pages: dict[int, PageInfo]
) -> tuple[list[Block], list[Finding]]:
    """Turn each `contents` block into its entries, read from the text layer: a paragraph for each
    line of contents, without the print page numbers; a list item for each line of an index (a
    block in the back half of the book), which keeps its numbers. A caption of the block comes
    first. On a scanned page, or when the text layer has nothing in the box, the block is
    Docling's table. The finding is a warning when the order is inferred from the layout
    (`_inferred`), since a wrong order without a warning is a failure (spec section 5)."""
    last = max(pages, default=0)
    out: list[Block] = []
    findings: list[Finding] = []
    for block in blocks:
        if block.kind != "contents":
            out.append(block)
            continue
        info = pages.get(block.page)
        readable = info is not None and not info.is_scanned and block.bbox is not None
        runs = _runs(pdf, info, block.bbox) if readable else []
        # chapter zones belong to contents; the letter headings of an index sit inside a column
        lines = (
            _reading_order(runs, info.width, chapter_starts=block.page <= last / 2) if runs else []
        )
        if not lines:
            out.append(replace(block, kind="table"))
            continue
        if block.caption.strip():
            out.append(Block("paragraph", block.caption, page=block.page))
        if block.page > last / 2:
            out += [Block("list_item", _text(line), page=block.page) for line in lines]
            message = "Index read again from the PDF text layer, in reading order."
        else:
            out += [Block("paragraph", _entry(line), page=block.page) for line in lines]
            message = "Contents read again from the PDF text layer, without print page numbers."
        level = "info"
        if _inferred(runs, info.width):
            level, message = (
                "warning",
                f"{message} Order inferred from the layout; check this page.",
            )
        findings.append(Finding(block.page, "contents_rebuilt", level, message))
    return out, findings
