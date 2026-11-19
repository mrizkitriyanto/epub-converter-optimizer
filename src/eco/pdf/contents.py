"""Contents and index pages, rebuilt from the PDF text layer in reading order (agent decision Q-23).

Docling reads a page of contents as a table (`document_index`), and its table model forces a
two-column page into a grid whose rows pair entries of both columns. On a page with a text layer
the entries are read again from that layer, one entry per line. The text runs are grouped into
lines by their height on the page; a page is read in columns only where its text has a gutter
(`_gutter`), and then a full-width line ends the columns above it, which are read left column
first. Otherwise the lines are read top to bottom, each left to right."""

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
_EDGE = 0.5  # pt: a run that starts this close to a column's edge starts at it
_ALIGN = 1.0  # pt: lines whose text starts this close together start a column
# The narrower of two columns is at least this share of the wider one. A column of labels beside
# their titles ("Chapter 1   Basics") is much narrower, and is one column with its titles.
_SAME_WIDTH = 0.4
_ROMAN = re.compile(r"m{0,3}(c[md]|d?c{0,3})(x[cl]|l?x{0,3})(i[xv]|v?i{0,3})")
_LEADER = r"(?:[.·…]\s*){4,}"  # a dot leader: four dots or more; "What next..." has three
_NUMBER_RUN = re.compile(rf"({_LEADER})?(\d+|[ivxlcdm]+)")
_NUMBER_AFTER_LEADER = re.compile(rf"(.*?\w.*?)\s*{_LEADER}(\d+|[ivxlcdm]+)")
_ENDS_IN_LEADER = re.compile(rf"\s*{_LEADER}$")
_LEADER_RUN = re.compile(_LEADER)
_CLOSING = ",;:)]"  # punctuation that belongs to the word before it


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
            # PDFium marks a hyphen at a line end with U+FFFE: keep it as a hyphen
            text = textpage.get_text_bounded(x0, y0, x1, y1).replace("￾", "-")
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


def _across(run: _Run, x: float, gap: float, start: float) -> bool:
    """True when a text run reaches into the gutter before `x` (`gap` wide), or starts in the
    right half of the left column, as a short title centred over the gutter does."""
    return run.left < x - _EDGE and (run.right > x - gap or run.left > (start + x) / 2)


def _gutter(runs: list[_Run]) -> tuple[float, float, float] | None:
    """Where the right column starts, how wide the gutter before it is at least, and where the
    left column starts, when the runs stand in two columns (or more); None when they do not.

    The gutter is a band one line high (the median height of the text) that only a few lines
    cross, fewer than either column has: those are full-width lines. Two lines or more start at
    its right edge, two lines or more lie left of it, and the two columns are of much the same
    width. Page numbers and dot leaders start no line, so a column of page numbers at the right
    margin is not a column. Of several such bands, the one fewest lines cross wins."""
    texts = [r for r in runs if _is_text(r)]
    if len(texts) < 4:
        return None
    gap = statistics.median(r.height for r in texts)
    start = min(r.left for r in texts)
    best: tuple[int, float] | None = None
    for x in sorted({r.left for r in texts}):
        right = [r for r in texts if r.left >= x - _EDGE]
        across = [r for r in texts if _across(r, x, gap, start)]
        left = [r for r in texts if r.left < x - _EDGE and not _across(r, x, gap, start)]
        starts = [r for r in right if r.left <= x + _ALIGN]
        if len(_rows(starts)) < 2 or len(_rows(left)) < 2:
            continue
        crossed = len(_rows(across))
        if crossed >= min(len(_rows(left)), len(_rows(right))):
            continue
        widths = max(r.right for r in left) - start, max(r.right for r in right) - x
        if min(widths) < _SAME_WIDTH * max(widths):
            continue
        if best is None or crossed < best[0]:
            best = (crossed, x)
    return None if best is None else (best[1], gap, start)


def _reading_order(runs: list[_Run]) -> list[list[_Run]]:
    """The lines of `runs` in reading order. In columns a full-width line ends the columns above
    it, which are read left column first; each column is read the same way, so a third column is
    found inside the second."""
    found = _gutter(runs)
    if found is None:
        return _rows(runs)
    x, gap, start = found
    lines: list[list[_Run]] = []
    left: list[_Run] = []
    right: list[_Run] = []
    for row in _rows(runs):
        if any(_is_text(r) and _across(r, x, gap, start) for r in row):
            lines += _reading_order(left) + _reading_order(right) + [row]
            left, right = [], []
        else:
            for run in row:
                (left if run.left < x - _EDGE else right).append(run)
    return lines + _reading_order(left) + _reading_order(right)


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
    Docling's table."""
    last = max(pages, default=0)
    out: list[Block] = []
    findings: list[Finding] = []
    for block in blocks:
        if block.kind != "contents":
            out.append(block)
            continue
        info = pages.get(block.page)
        readable = info is not None and not info.is_scanned and block.bbox is not None
        lines = _reading_order(_runs(pdf, info, block.bbox)) if readable else []
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
        findings.append(Finding(block.page, "contents_rebuilt", "info", message))
    return out, findings
